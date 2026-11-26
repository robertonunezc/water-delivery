from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from clients.models import Client, CreditTransaction
from clients.services.client_debt_service import get_client_display_current_debt
from orders.models import Order

logger = logging.getLogger(__name__)
ZERO = Decimal('0.00')
CREDIT_ORIGIN_TYPES = ('purchase', 'payment_reversal', 'transfer_in')


@dataclass(frozen=True)
class CreditReconciliationSummary:
    client: Client
    credit_account: Client
    ledger_debt: Decimal
    open_credit_total: Decimal
    open_order_count: int

    @property
    def difference(self) -> Decimal:
        return self.ledger_debt - self.open_credit_total

    @property
    def is_balanced(self) -> bool:
        return self.difference == ZERO


@dataclass(frozen=True)
class DebtRecalculationResult:
    client: Client
    credit_account: Client
    debt_before: Decimal
    debt_after: Decimal
    open_order_count: int
    transaction: CreditTransaction | None = None

    @property
    def delta(self) -> Decimal:
        return self.debt_after - self.debt_before

    @property
    def changed(self) -> bool:
        return self.debt_before != self.debt_after


def _has_pending_credit_marker(order: Order) -> bool:
    return any(
        payment.method == 'pending_credit' and payment.status == 'pending'
        for payment in order.payments.all()
    )


def _has_outstanding_credit_ledger(order: Order) -> bool:
    summary = CreditTransaction.objects.filter(reference_order=order).aggregate_summary()
    return (summary['total_purchases'] - summary['total_payments']) > ZERO


def has_open_credit_exposure(order: Order) -> bool:
    """Return True when an order has either a pending credit marker or positive credit ledger debt."""
    return _has_pending_credit_marker(order) or _has_outstanding_credit_ledger(order)


def _open_credit_orders_for_account(
    credit_account: Client,
    *,
    scope_client: Client | None = None,
) -> list[Order]:
    orders = Order.objects.active().unpaid().for_credit_accounts([credit_account.pk])
    if scope_client is not None and scope_client.type != 'corporate':
        orders = orders.filter(client=scope_client)

    credit_tx_order_ids = CreditTransaction.objects.filter(
        client=credit_account,
        transaction_type__in=CREDIT_ORIGIN_TYPES,
        reference_order__isnull=False,
    ).values('reference_order_id')

    candidates = list(
        orders.filter(
            Q(payments__method='pending_credit', payments__status='pending')
            | Q(pk__in=credit_tx_order_ids)
        )
        .prefetch_related('payments')
        .distinct()
    )
    return [order for order in candidates if has_open_credit_exposure(order)]


def _open_credit_orders(client: Client) -> list[Order]:
    return _open_credit_orders_for_account(
        client.get_credit_account(),
        scope_client=client,
    )


def _remaining_amount(order: Order) -> Decimal:
    total = Decimal(str(order.total_amount))
    paid = Decimal(str(order.total_paid))
    return max(total - paid, ZERO)


def get_credit_reconciliation_summary(client: Client) -> CreditReconciliationSummary:
    credit_account = client.get_credit_account()
    open_orders = _open_credit_orders(client)
    open_total = sum(
        (_remaining_amount(order) for order in open_orders),
        ZERO,
    )
    return CreditReconciliationSummary(
        client=client,
        credit_account=credit_account,
        ledger_debt=get_client_display_current_debt(client),
        open_credit_total=open_total,
        open_order_count=len(open_orders),
    )


def get_credit_reconciliation_warning(client: Client) -> dict[str, object] | None:
    summary = get_credit_reconciliation_summary(client)
    if summary.is_balanced:
        return None
    return {
        'summary': summary,
        'message': (
            'La deuda registrada no coincide con los pedidos a crédito pendientes. '
            f'Deuda registrada: ${summary.ledger_debt:.2f}. '
            f'Pedidos pendientes: ${summary.open_credit_total:.2f}.'
        ),
    }


def validate_global_debt_decrease_allowed(client: Client) -> None:
    summary = get_credit_reconciliation_summary(client)
    if summary.open_order_count == 0:
        return
    raise ValueError(
        'Selecciona pedidos a crédito para aplicar pagos, ajustes o correcciones '
        'cuando existen pedidos a crédito pendientes. '
        f'Pedidos pendientes: ${summary.open_credit_total:.2f}.'
    )


@transaction.atomic
def recalculate_client_debt(
    client: Client,
    user: AbstractBaseUser | None = None,
) -> DebtRecalculationResult:
    """Recalculate credit account current_debt from active unpaid credit orders."""
    credit_account_id = client.get_credit_account().pk
    credit_account = Client.objects.select_for_update().get(pk=credit_account_id)
    open_orders = _open_credit_orders_for_account(credit_account)
    debt_before = Decimal(str(credit_account.current_debt))
    debt_after = sum((_remaining_amount(order) for order in open_orders), ZERO)

    if debt_after == debt_before:
        return DebtRecalculationResult(
            client=client,
            credit_account=credit_account,
            debt_before=debt_before,
            debt_after=debt_after,
            open_order_count=len(open_orders),
            transaction=None,
        )

    credit_account.current_debt = debt_after
    credit_account.save(update_fields=['current_debt', 'updated_at'])

    transaction_type = 'correction' if debt_after < debt_before else 'adjustment'
    tx = CreditTransaction.objects.create(
        client=credit_account,
        transaction_type=transaction_type,
        amount=abs(debt_after - debt_before),
        debt_before=debt_before,
        debt_after=debt_after,
        credit_limit_before=credit_account.credit_limit,
        credit_limit_after=credit_account.credit_limit,
        date=timezone.localdate(),
        created_by=user,
        notes=(
            f'Recálculo manual de deuda basado en {len(open_orders)} pedido(s) '
            f'a crédito pendiente(s) (${debt_before:.2f} → ${debt_after:.2f}).'
        ),
    )
    logger.info(
        'Recalculated debt for credit_account=%s (requested from client=%s) '
        'from %s to %s by user=%s',
        credit_account.pk,
        client.pk,
        debt_before,
        debt_after,
        getattr(user, 'pk', None),
    )
    return DebtRecalculationResult(
        client=client,
        credit_account=credit_account,
        debt_before=debt_before,
        debt_after=debt_after,
        open_order_count=len(open_orders),
        transaction=tx,
    )
