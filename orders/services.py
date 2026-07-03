from datetime import date
from decimal import Decimal
from django.db import transaction
from django.db.models import Count, QuerySet, Sum
from django.utils import timezone
from clients.models import Client
from core import models
from orders.models import Order, OrderProduct, OrderStatus
from product.models import ProductClientPrice
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def get_sales_snapshot(start_date: date, end_date: date) -> dict[str, object]:
    """Return compact completed-order sales metrics for a date range."""
    completed_orders = Order.objects.completed_in_date_range(start_date, end_date)
    totals = completed_orders.aggregate(
        total_orders=Count('id'),
        total_amount=Sum('total_amount'),
        total_discount=Sum('discount'),
    )
    total_orders = totals['total_orders'] or 0
    total_amount = totals['total_amount'] or Decimal('0.00')
    total_discount = totals['total_discount'] or Decimal('0.00')
    average_ticket = total_amount / total_orders if total_orders else Decimal('0.00')

    from payment.models import PAYMENT_METHOD_CHOICES, Payment

    method_labels = dict(PAYMENT_METHOD_CHOICES)
    payment_rows = (
        Payment.objects.filter(
            order__in=completed_orders,
            status='completed',
        )
        .exclude(method='pending_credit')
        .values('method')
        .annotate(
            total_amount=Sum('amount'),
            payment_count=Count('id'),
        )
        .order_by('method')
    )
    payment_methods = [
        {
            'method': row['method'],
            'label': method_labels.get(row['method'], row['method']),
            'total_amount': row['total_amount'] or Decimal('0.00'),
            'payment_count': row['payment_count'],
        }
        for row in payment_rows
    ]
    return {
        'total_orders': total_orders,
        'total_amount': total_amount,
        'average_ticket': average_ticket,
        'total_discount': total_discount,
        'payment_methods': payment_methods,
    }


@dataclass
class OrderData:
    id: int
    client_id: int
    total_amount: Decimal
    status: str
    created_at: datetime
    items: List = None


def get_or_create_order(client=None, order_id=None, owner=None) -> OrderData:
    if not client and not order_id:
        raise ValueError("Se requiere un cliente o un ID de orden para obtener o crear una orden.")
    if order_id:
        try:
            order = Order.objects.get(pk=order_id)
            return OrderData(
                id=order.id,
                client_id=order.client_id,
                total_amount=order.total_amount,
                status=order.status,
                created_at=order.created_at,
                items=list(order.items.all())
            )
        except Order.DoesNotExist:
            pass

    existing_orders = get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=client)
    if existing_orders:
        return existing_orders[0]

    order = Order.objects.create(client=client, total_amount=Decimal('0.00'), owner=owner)
    return OrderData(
        id=order.id,
        client_id=order.client_id,
        total_amount=order.total_amount,
        status=order.status,
        created_at=order.created_at,
        items=list(order.items.all())
    )


def get_client_orders(date: date, status: OrderStatus, client: Client) -> List[OrderData]:
    orders = Order.objects.filter(client=client, created_at__date=date, status=status.value)
    return [
        OrderData(
            id=order.id,
            client_id=order.client_id,
            total_amount=order.total_amount,
            status=order.status,
            created_at=order.created_at,
            items=list(order.items.all())
        )
        for order in orders
    ]


def get_product_price_for_client(product, client):
    try:    
        price_entry = ProductClientPrice.objects.get(product=product, client=client)
        return Decimal(str(price_entry.price))
    except ProductClientPrice.DoesNotExist:
        base_price = getattr(product, 'base_price', None)
        if base_price is not None:
            return Decimal(str(base_price))
        return Decimal(str(getattr(product, 'price', 0.0)))
    
def update_order(order: Order, quantity: int, product, client: Client, discount: Decimal = Decimal('0.00')) -> Order:
    unit_price = get_product_price_for_client(product, client)
    if not isinstance(unit_price, Decimal):
        unit_price = Decimal(str(unit_price))
    order.discount = discount

    if quantity <= 0:
        OrderProduct.objects.filter(order=order, product=product).delete()
        order.total_amount = calculate_order_total(order)
        order.save(update_fields=['discount', 'subtotal_amount', 'total_amount'])
        return order

    # Handle potential duplicates due to race conditions or previous bugs
    order_products = list(OrderProduct.objects.filter(order=order, product=product))
    if order_products:
        order_product = order_products[0]
        if len(order_products) > 1:
            # Delete duplicates
            duplicate_ids = [op.pk for op in order_products[1:]]
            OrderProduct.objects.filter(pk__in=duplicate_ids).delete()
    else:
        order_product = OrderProduct.objects.create(
            order=order, 
            product=product, 
            quantity=0, 
            unit_price=unit_price
        )
    order_product.quantity = int(quantity)
    order_product.unit_price = unit_price
    order_product.save()
    # update order totals and return the order
    order.total_amount = calculate_order_total(order)
    order.save(update_fields=['discount', 'subtotal_amount', 'total_amount'])
    return order

def calculate_order_total(order) -> Decimal:
    subtotal = Decimal('0.00')
    for item in order.items.all():
        unit = Decimal(str(item.unit_price))
        qty = Decimal(str(item.quantity))
        subtotal += unit * qty
    discount = Decimal(str(order.discount or 0))
    total = max(Decimal("0"), subtotal - discount)
    if hasattr(order, 'subtotal_amount'):
        order.subtotal_amount = subtotal
    return total

def get_logger(name: str):
    """Return a logger for the orders module.

    This simple helper centralizes logger creation so views can call
    `services.get_logger(__name__)` without needing additional imports.
    """
    return logging.getLogger(name)


def _audit_user(user: object | None = None) -> object | None:
    """Return a persisted user for audit fields, or None for anonymous/system work."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return user


def _mark_cancellation_review_required(
    order: Order,
    reason: str,
    user: object | None = None,
) -> Dict[str, object]:
    """Persist cancellation review metadata and return a service failure result."""
    order.cancellation_review_required = True
    order.cancellation_review_reason = reason
    order.cancellation_requested_at = timezone.now()
    order.cancellation_requested_by = _audit_user(user)
    order.save(
        update_fields=[
            'cancellation_review_required',
            'cancellation_review_reason',
            'cancellation_requested_at',
            'cancellation_requested_by',
            'updated_at',
        ]
    )
    return {
        'success': False,
        'review_required': True,
        'error': reason,
    }


def _mark_cancellation_review_required_by_id(
    order_id: int,
    reason: str,
    user: object | None = None,
) -> Dict[str, object]:
    order = Order.objects.get(pk=order_id)
    return _mark_cancellation_review_required(order=order, reason=reason, user=user)


def _clear_cancellation_review(order: Order) -> None:
    order.cancellation_review_required = False
    order.cancellation_review_reason = None
    order.cancellation_requested_at = None
    order.cancellation_requested_by = None


def _get_added_balance_amount(order: Order) -> Decimal:
    total = order.client.balance_transactions.filter(
        reference_order=order,
        transaction_type='added_in_order',
    ).aggregate(total=Sum('amount'))['total']
    return total or Decimal('0.00')


def _reverse_added_balance(
    order: Order,
    amount: Decimal,
    user: object | None = None,
) -> None:
    if amount <= 0:
        return

    from clients.services import balance_service

    transaction_result = balance_service.reverse_added_order_balance(
        client=order.client,
        amount=amount,
        user=user,
        reference_order=order,
    )
    if transaction_result is None:
        raise ValueError(
            'El cliente no tiene saldo suficiente para revertir el saldo agregado en la venta.'
        )


def _reverse_completed_balance_payments(
    order: Order,
    user: object | None = None,
) -> None:
    from clients.services import balance_service

    balance_payments = order.payments.select_for_update().filter(
        method='balance',
        status='completed',
    )
    for payment in balance_payments:
        balance_service.reverse_balance_payment(payment=payment, user=user)


def _reverse_credit_payment_transactions(
    order: Order,
    user: object | None = None,
) -> None:
    from clients.services import balance_service

    credit_payments = order.client.credit_transactions.filter(
        reference_order=order,
        transaction_type__in=['payment', 'payment_from_balance'],
    ).order_by('created_at', 'id')
    for credit_payment in credit_payments:
        balance_service.reverse_credit_payment(
            client=order.client,
            amount=credit_payment.amount,
            user=user,
            reference_order=order,
            reference_payment=credit_payment.reference_payment,
            notes=f'Reversión de pago de deuda por cancelación de pedido #{order.id}',
        )


def _reverse_credit_purchase_transactions(
    order: Order,
    user: object | None = None,
) -> None:
    from clients.services import balance_service

    credit_purchases = order.client.credit_transactions.filter(
        reference_order=order,
        transaction_type='purchase',
    ).order_by('created_at', 'id')
    for credit_purchase in credit_purchases:
        balance_service.reverse_credit_purchase(
            client=order.client,
            amount=credit_purchase.amount,
            user=user,
            reference_order=order,
            reference_payment=credit_purchase.reference_payment,
            notes=f'Reversión de compra a crédito por cancelación de pedido #{order.id}',
        )


def _mark_payments_reversed(order: Order) -> int:
    return order.payments.select_for_update().filter(
        status__in=['completed', 'pending'],
    ).update(status='reversed', updated_at=timezone.now())


def _cancel_order_in_transaction(
    order: Order,
    user: object | None = None,
) -> Dict[str, object]:
    locked_order = (
        Order.objects.select_for_update()
        .select_related('client')
        .get(pk=order.pk)
    )
    locked_client = Client.objects.select_for_update().get(pk=locked_order.client_id)
    locked_order.client = locked_client

    if locked_order.status == OrderStatus.CANCELLED.value:
        return {
            'success': True,
            'skipped': True,
            'message': f'Pedido #{locked_order.id} ya estaba cancelado.',
        }

    if locked_order.invoice_links.exists():
        return _mark_cancellation_review_required(
            order=locked_order,
            reason='El pedido ya está vinculado a una factura y requiere revisión.',
            user=user,
        )

    added_balance_amount = _get_added_balance_amount(locked_order)
    if added_balance_amount > locked_client.balance:
        return _mark_cancellation_review_required(
            order=locked_order,
            reason=(
                'El cliente no tiene saldo suficiente para revertir el saldo '
                'agregado en la venta. Requiere revisión.'
            ),
            user=user,
        )

    _reverse_added_balance(locked_order, added_balance_amount, user=user)
    _reverse_completed_balance_payments(locked_order, user=user)
    _reverse_credit_payment_transactions(locked_order, user=user)
    _reverse_credit_purchase_transactions(locked_order, user=user)
    payments_reversed = _mark_payments_reversed(locked_order)

    locked_order.status = OrderStatus.CANCELLED.value
    _clear_cancellation_review(locked_order)
    locked_order.save(
        update_fields=[
            'status',
            'cancellation_review_required',
            'cancellation_review_reason',
            'cancellation_requested_at',
            'cancellation_requested_by',
            'updated_at',
        ]
    )

    logger.info(
        f"Order #{locked_order.id} cancelled by "
        f"{user.username if user else 'system'} - client_id={locked_order.client_id}, "
        f"payments_reversed={payments_reversed}"
    )
    return {
        'success': True,
        'skipped': False,
        'message': f'Pedido #{locked_order.id} cancelado correctamente.',
        'payments_reversed': payments_reversed,
    }


def cancel_order(order: Order, user: object | None = None) -> Dict[str, object]:
    """Cancel an order by status and reverse internal financial effects.

    Returns:
        dict with success status and message/error details.
    """
    try:
        with transaction.atomic():
            return _cancel_order_in_transaction(order=order, user=user)
    except ValueError as exc:
        return _mark_cancellation_review_required_by_id(
            order_id=order.pk,
            reason=str(exc),
            user=user,
        )


def cancel_pending_order(order: Order, user: object | None = None) -> Dict[str, object]:
    """Backward-compatible wrapper for status-based order cancellation."""
    return cancel_order(order=order, user=user)


# Payment Processing Functions
# These functions coordinate payment between Client balance/credit and Order


@transaction.atomic
def process_order_payment(
    client: Client,
    order_amount: Decimal,
    payment_method: str = "auto",
    order: Optional[Order] = None,
    user=None,
    credit_note: Optional[str] = None,
) -> dict:
    """
    Process payment for an order using different strategies.

    This function coordinates balance and credit usage but delegates
    the actual mutations to the balance_service.

    Args:
        client: Client making the payment
        order_amount: Amount to process
        payment_method: 'auto', 'balance', 'credit', 'mixed'
        order: Order object for transaction reference
        user: User performing the operation
        credit_note: Optional note appended to the payment notes

    Returns:
        dict with success status and payment breakdown
    """
    from clients.services import balance_service

    remaining_amount = order_amount
    balance_used = Decimal("0")
    credit_used = Decimal("0")
    print("preferred method", payment_method)
    if payment_method == "balance":
        # Try to pay entirely with balance
        if client.balance >= order_amount:
            balance_used = order_amount
            remaining_amount = Decimal("0")
        else:
            return {
                "success": False,
                "error": f"Insufficient balance. Available: ${client.balance:.2f}, "
                f"Required: ${order_amount:.2f}",
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
            }

    elif payment_method == "credit":
        # Check if client can use credit
        if not client.can_use_credit_for_payment():
            return {
                "success": False,
                "error": "Client is not allowed to pay with credit at this time.",
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
            }

        # Try to pay entirely with credit
        available_credit = client.get_available_credit()
        if available_credit >= order_amount:
            credit_used = order_amount
            remaining_amount = Decimal("0")
        else:
            return {
                "success": False,
                "error": f"Insufficient credit. Available: ${available_credit:.2f}, "
                f"Required: ${order_amount:.2f}",
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
            }
    
    else:  # 'auto' or 'mixed'
        # First, use available balance
        balance_used = min(client.balance, remaining_amount)
        remaining_amount -= balance_used

        # Then, use credit if needed and available
        if remaining_amount > 0:
            # Check if client can use credit
            if not client.can_use_credit_for_payment():
                return {
                    "success": False,
                    "error": f"Client cannot use credit. Need additional "
                    f"${remaining_amount:.2f} in balance.",
                    "balance_used": Decimal("0"),
                    "credit_used": Decimal("0"),
                    "balance_available": client.balance,
                    "credit_available": Decimal("0"),
                }

            available_credit = Decimal(str(client.get_available_credit()))
            credit_used = min(available_credit, remaining_amount)
            remaining_amount -= credit_used

    # Check if we can cover the full amount
    if remaining_amount > 0:
        return {
            "success": False,
            "error": f"Insufficient funds. Need additional ${remaining_amount:.2f}",
            "balance_used": Decimal("0"),
            "credit_used": Decimal("0"),
            "balance_available": client.balance,
            "credit_available": client.get_available_credit(),
        }

    if credit_used > 0:
        from clients.services.pending_payment_service import client_has_overdue_credit

        if client_has_overdue_credit(client):
            return {
                "success": False,
                "error": (
                    "El cliente tiene créditos vencidos y no puede realizar nuevas "
                    "ventas a crédito."
                ),
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
            }

    # Actually process the payment using balance_service
    if balance_used > 0:
        balance_service.deduct_balance(
            client=client,
            amount=balance_used,
            transaction_type="payment",
            user=user,
            reference_order=order,
            notes=f"Pago de orden con saldo - ${balance_used:.2f}",
        )

    if credit_used > 0:
        notes = f"Compra a crédito - ${credit_used:.2f}"
        if credit_note:
            notes = f"{notes}. {credit_note}"
        balance_service.add_debt(
            client=client,
            amount=credit_used,
            transaction_type="purchase",
            user=user,
            reference_order=order,
            notes=notes,
        )

    return {
        "success": True,
        "balance_used": balance_used,
        "credit_used": credit_used,
        "remaining_balance": client.balance,
        "current_debt": client.current_debt,
        "available_credit": client.get_available_credit(),
    }


# Order Status Management Functions
# These functions handle bulk order status transitions with proper audit trails


@transaction.atomic
def mark_orders_as_completed(queryset, user=None) -> Dict[str, int]:
    """
    Mark multiple orders as completed.

    This function:
    1. Validates each order can be completed
    2. Updates status to COMPLETED
    3. Logs the operation with user information

    Args:
        queryset: QuerySet of Order objects to mark as completed
        user: User performing the operation (for audit trail)

    Returns:
        dict with 'updated' count and 'skipped' count
    """
    updated = 0
    skipped = 0

    for order in queryset:
        # Skip if already completed
        if order.status == OrderStatus.COMPLETED.value:
            logger.info(f"Order #{order.id} already completed, skipping")
            skipped += 1
            continue

        # Update status
        order.status = OrderStatus.COMPLETED.value
        order.save(update_fields=['status', 'updated_at'])

        logger.info(
            f"Order #{order.id} marked as COMPLETED by {user.username if user else 'system'}"
        )
        updated += 1

    return {
        'updated': updated,
        'skipped': skipped,
    }


@transaction.atomic
def cancel_orders(queryset: QuerySet, user: object | None = None) -> Dict[str, int]:
    """
    Cancel multiple orders.

    This function:
    1. Delegates each order to the single-order cancellation service
    2. Reverses internal financial effects when cancellation succeeds
    3. Marks blocked cancellations for staff review

    Args:
        queryset: QuerySet of Order objects to cancel
        user: User performing the operation (for audit trail)

    Returns:
        dict with 'updated' count and 'skipped' count
    """
    updated = 0
    skipped = 0
    review_required = 0

    for order in queryset:
        result = cancel_order(order=order, user=user)
        if result.get('success') and not result.get('skipped'):
            updated += 1
            continue
        if result.get('review_required'):
            review_required += 1
            skipped += 1
            continue
        skipped += 1

    return {
        'updated': updated,
        'skipped': skipped,
        'review_required': review_required,
    }


@transaction.atomic
def mark_orders_as_pending(queryset, user=None) -> Dict[str, int]:
    """
    Mark multiple orders as pending.

    This function:
    1. Updates status to PENDING
    2. Logs the operation with user information

    This is typically used to revert orders to pending status for corrections.

    Args:
        queryset: QuerySet of Order objects to mark as pending
        user: User performing the operation (for audit trail)

    Returns:
        dict with 'updated' count and 'skipped' count
    """
    updated = 0
    skipped = 0

    for order in queryset:
        # Skip if already pending
        if order.status == OrderStatus.PENDING.value:
            logger.info(f"Order #{order.id} already pending, skipping")
            skipped += 1
            continue

        # Update status
        order.status = OrderStatus.PENDING.value
        order.save(update_fields=['status', 'updated_at'])

        logger.info(
            f"Order #{order.id} marked as PENDING by {user.username if user else 'system'}"
        )
        updated += 1

    return {
        'updated': updated,
        'skipped': skipped,
    }
