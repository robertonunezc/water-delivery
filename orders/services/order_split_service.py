from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from clients.models import Client, CreditTransaction
from orders.models import Order, OrderProduct, OrderSplit, OrderStatus
from payment.models import Payment
from payment.services import get_unpaid_amount

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


class OrderSplitError(ValueError):
    """The split cannot preserve the order's quantities or financial records."""


def _portion(amount: Decimal, proportion: Decimal) -> Decimal:
    return (amount * proportion).quantize(CENT)


def _validate_quantities(items: list[OrderProduct], quantities: dict[int, int]) -> None:
    if set(quantities) - {item.pk for item in items}:
        raise OrderSplitError("Los productos cambiaron. Recargue el pedido.")
    if any(not 0 <= quantities.get(item.pk, 0) <= item.quantity for item in items):
        raise OrderSplitError("La cantidad a dividir excede los productos disponibles.")
    if not any(quantities.values()) or not any(
        item.quantity > quantities.get(item.pk, 0) for item in items
    ):
        raise OrderSplitError("Ambos pedidos deben conservar al menos un producto.")


def _create_child(order: Order, subtotal: Decimal, proportion: Decimal) -> Order:
    discount = _portion(order.discount, proportion)
    child = Order.objects.create(
        client=order.client, status=order.status, type=order.type, owner=order.owner,
        notes=f"Dividida de Orden #{order.pk}", subtotal_amount=subtotal,
        discount=discount, total_amount=subtotal - discount,
        cantidad_cobrada=(
            _portion(order.cantidad_cobrada, proportion)
            if order.cantidad_cobrada is not None else None
        ),
    )
    # auto_now_add ignores order_date on creation; a split keeps the sale date.
    Order.objects.filter(pk=child.pk).update(order_date=order.order_date)
    child.order_date = order.order_date
    return child


def _move_items(
    child: Order, items: list[OrderProduct], quantities: dict[int, int],
) -> None:
    for item in items:
        moved = quantities.get(item.pk, 0)
        if not moved:
            continue
        OrderProduct.objects.create(
            order=child, product=item.product, quantity=moved,
            unit_price=item.unit_price, note=item.note,
        )
        item.quantity -= moved
        if item.quantity:
            item.save(update_fields=["quantity", "updated_at"])
        else:
            item.delete()


def _update_source_totals(order: Order, child: Order, subtotal: Decimal) -> None:
    order.subtotal_amount = subtotal - child.subtotal_amount
    order.discount -= child.discount
    order.total_amount = order.subtotal_amount - order.discount
    if order.cantidad_cobrada is not None:
        order.cantidad_cobrada -= child.cantidad_cobrada
    order.save(update_fields=[
        "subtotal_amount", "discount", "total_amount", "cantidad_cobrada", "updated_at",
    ])


def _split_payment(
    payment: Payment, child: Order, amount: Decimal, user: AbstractBaseUser | None,
) -> Payment:
    proportion = amount / payment.amount if payment.amount else ZERO
    child_balance = _portion(payment.balance_used, proportion)
    child_credit = _portion(payment.credit_used, proportion)
    child_payment = Payment(
        order=child, client=payment.client, amount=amount, method=payment.method,
        status=payment.status, balance_used=child_balance, credit_used=child_credit,
        created_by=user,
    )
    child_payment.save(apply_accounting=False)
    Payment.objects.filter(pk=child_payment.pk).update(date=payment.date)
    Payment.objects.filter(pk=payment.pk).update(
        amount=payment.amount - amount, balance_used=payment.balance_used - child_balance,
        credit_used=payment.credit_used - child_credit, updated_at=timezone.now(),
    )
    child_payment.date = payment.date
    return child_payment


def _transfer_credit(
    pending: Payment, child_pending: Payment, user: AbstractBaseUser | None,
) -> None:
    entries = CreditTransaction.objects.filter(reference_order=pending.order)
    purchase = (
        entries.filter(transaction_type="purchase").order_by("created_at", "pk").first()
    )
    if purchase is None:
        raise OrderSplitError(
            "El crédito del pedido no tiene una compra vinculada. Requiere revisión."
        )
    account = Client.objects.select_for_update().get(pk=purchase.client_id)
    if entries.exclude(client=account).exists() or entries.exclude(
        transaction_type__in=["purchase", "purchase_reversal"],
    ).exists():
        raise OrderSplitError("El crédito tiene cuentas o ajustes ambiguos. Requiere revisión.")
    summary = entries.aggregate_summary()
    if summary["total_purchases"] - summary["total_payments"] != pending.amount:
        raise OrderSplitError(
            "La deuda del pedido no coincide con su crédito pendiente. Requiere revisión."
        )
    amount = child_pending.amount
    if amount > account.current_debt:
        raise OrderSplitError(
            "El crédito a dividir excede la deuda registrada. Requiere revisión."
        )
    _record_credit_transfer(account, pending, child_pending, user)


def _record_credit_transfer(
    account: Client, pending: Payment, child_pending: Payment,
    user: AbstractBaseUser | None,
) -> None:
    amount = child_pending.amount
    if amount <= ZERO:
        return
    common = dict(
        client=account, amount=amount, created_by=user, date=timezone.localdate(),
        credit_limit_before=account.credit_limit, credit_limit_after=account.credit_limit,
        notes=(
            f"Redistribución por división del pedido #{pending.order_id} "
            f"a #{child_pending.order_id}"
        ),
    )
    # Reassign existing debt without charging again or rewriting the original sale.
    CreditTransaction.objects.create(
        **common, transaction_type="purchase_reversal", reference_order=pending.order,
        reference_payment=pending, debt_before=account.current_debt,
        debt_after=account.current_debt - amount,
    )
    CreditTransaction.objects.create(
        **common, transaction_type="purchase", reference_order=child_pending.order,
        reference_payment=child_pending, debt_before=account.current_debt - amount,
        debt_after=account.current_debt,
    )


def _split_completed_payments(
    payments: list[Payment], child: Order, proportion: Decimal,
    user: AbstractBaseUser | None,
) -> None:
    real_payments = [
        p for p in payments if p.status == "completed" and p.method != "pending_credit"
    ]
    total_paid = sum((p.amount for p in real_payments), ZERO)
    target = _portion(total_paid, proportion)
    processed = ZERO
    allocated = ZERO
    for payment in real_payments:
        processed += payment.amount
        cumulative = _portion(target, processed / total_paid) if total_paid else ZERO
        _split_payment(payment, child, cumulative - allocated, user)
        allocated = cumulative
    for payment in payments:
        if payment.status == "completed" and payment.method == "pending_credit":
            _split_payment(payment, child, _portion(payment.amount, proportion), user)


def _split_payments(
    order: Order, child: Order, proportion: Decimal, user: AbstractBaseUser | None,
) -> None:
    payments = list(order.payments.select_for_update().filter(
        Q(status="completed") | Q(method="pending_credit", status="pending"),
    ).order_by("pk"))
    pending = [p for p in payments if p.method == "pending_credit" and p.status == "pending"]
    if len(pending) > 1:
        raise OrderSplitError("El pedido tiene varios créditos pendientes. Requiere revisión.")
    _split_completed_payments(payments, child, proportion, user)
    if pending:
        marker = pending[0]
        amount = get_unpaid_amount(child)
        if marker.amount != get_unpaid_amount(order) + amount:
            raise OrderSplitError(
                "El crédito pendiente no coincide con el total a dividir. Requiere revisión."
            )
        child_pending = _split_payment(marker, child, amount, user)
        _transfer_credit(marker, child_pending, user)


@transaction.atomic
def split_order(
    order: Order, quantities: dict[int, int], user: AbstractBaseUser | None = None,
) -> Order:
    """Split a completed sale, preserving money received and total credit debt."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != OrderStatus.COMPLETED.value:
        raise OrderSplitError("Solo se pueden dividir pedidos completados.")
    items = list(order.items.select_for_update().order_by("pk"))
    _validate_quantities(items, quantities)
    subtotal = sum((item.quantity * item.unit_price for item in items), ZERO)
    child_subtotal = sum(
        (quantities.get(item.pk, 0) * item.unit_price for item in items), ZERO,
    )
    if subtotal <= ZERO or order.total_amount != subtotal - order.discount:
        raise OrderSplitError(
            "El total del pedido no coincide con sus productos. Requiere revisión."
        )
    child = _create_child(order, child_subtotal, child_subtotal / subtotal)
    proportion = child.total_amount / order.total_amount if order.total_amount else ZERO
    _move_items(child, items, quantities)
    _update_source_totals(order, child, subtotal)
    _split_payments(order, child, proportion, user)
    OrderSplit.objects.create(source_order=order, child_order=child, split_by=user)
    return child


def _legacy_credit_children(order: Order) -> list[Order]:
    child_ids = OrderSplit.objects.filter(source_order=order).values("child_order_id")
    children = list(
        Order.objects.select_for_update().filter(pk__in=child_ids).order_by("pk")
    )
    candidates = []
    for child in children:
        has_credit = CreditTransaction.objects.filter(reference_order=child).exists()
        if has_credit or child.payments.filter(method="pending_credit").exists():
            continue
        if child.client_id != order.client_id or child.status != OrderStatus.COMPLETED.value:
            raise OrderSplitError(
                "La división contiene pedidos cancelados o de otro cliente. Requiere revisión."
            )
        if child.split_as_source.exists():
            raise OrderSplitError(
                "La división contiene subdivisiones históricas. Requiere revisión."
            )
        candidates.append(child)
    return candidates


def _validate_legacy_credit(order: Order, children: list[Order]) -> Payment:
    family_ids = [order.pk, *(child.pk for child in children)]
    if Payment.objects.filter(
        order_id__in=family_ids, status="completed",
    ).exclude(method="pending_credit").exists():
        raise OrderSplitError("La división ya tiene pagos reales. Requiere revisión manual.")
    markers = list(order.payments.select_for_update().filter(
        method="pending_credit", status="pending",
    ))
    if len(markers) != 1:
        raise OrderSplitError(
            "Se requiere exactamente un crédito pendiente en la orden original."
        )
    expected = get_unpaid_amount(order) + sum(
        (get_unpaid_amount(child) for child in children), ZERO,
    )
    if markers[0].amount != expected:
        raise OrderSplitError(
            "El crédito no coincide con la suma de los pedidos divididos. Requiere revisión."
        )
    return markers[0]


@transaction.atomic
def repair_split_order_credit(order: Order, user: AbstractBaseUser | None = None) -> int:
    """Repair unambiguous unpaid legacy splits; preserve debt and allow safe retries."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != OrderStatus.COMPLETED.value or order.type != "credito":
        raise OrderSplitError("La orden original debe estar completada y ser a crédito.")
    children = _legacy_credit_children(order)
    if not children:
        return 0
    pending = _validate_legacy_credit(order, children)
    for child in children:
        amount = get_unpaid_amount(child)
        child_pending = _split_payment(pending, child, amount, user)
        _transfer_credit(pending, child_pending, user)
        Order.objects.filter(pk=child.pk).update(type="credito", updated_at=timezone.now())
        pending.refresh_from_db()
    return len(children)
