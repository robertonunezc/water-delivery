from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q

from clients.models import Client, CreditTransaction
from clients.services.client_debt_service import get_client_display_current_debt
from orders.models import Order

ZERO = Decimal('0.00')


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


def _open_credit_orders(client: Client) -> list[Order]:
    credit_account = client.get_credit_account()
    credit_transactions = CreditTransaction.objects.filter(
        transaction_type='purchase',
        reference_order__isnull=False,
    )
    if client.type == 'corporate':
        credit_transactions = credit_transactions.filter(
            Q(reference_order__client=client)
            | Q(reference_order__client__corporate=client),
        )
    else:
        credit_transactions = credit_transactions.filter(
            client=credit_account,
            reference_order__client=client,
        )

    credit_order_ids = credit_transactions.values('reference_order_id')
    return list(
        Order.objects.active()
        .unpaid()
        .filter(
            pk__in=credit_order_ids,
            payments__method='pending_credit',
            payments__status='pending',
        )
        .prefetch_related('payments')
        .distinct()
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
