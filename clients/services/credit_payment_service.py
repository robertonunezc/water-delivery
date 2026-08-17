from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from clients.models import Client, CreditTransaction
from orders.models import Order
from payment import services as payment_services


class CreditManagementOrderError(ValueError):
    """Raised when selected credit-management orders are invalid."""


def get_open_credit_orders_for_credit_management(client: Client) -> list[Order]:
    """Return open credit orders selectable from the client's credit screen."""
    credit_transactions = CreditTransaction.objects.filter(
        transaction_type='purchase',
        reference_order__isnull=False,
    )
    if client.type == 'corporate':
        credit_transactions = credit_transactions.filter(
            reference_order__client__corporate=client,
        )
    else:
        credit_transactions = credit_transactions.filter(
            client=client.get_credit_account(),
            reference_order__client=client,
        )

    credit_order_ids = credit_transactions.values('reference_order_id')
    orders = (
        Order.objects.active()
        .unpaid()
        .filter(
            pk__in=credit_order_ids,
            payments__method='pending_credit',
            payments__status='pending',
        )
        .select_related('client', 'client__corporate')
        .prefetch_related('payments')
        .distinct()
        .order_by('-order_date', '-id')
    )
    return list(orders)


def get_selected_credit_orders_for_credit_management(
    client: Client,
    order_ids: list[int],
) -> list[Order]:
    """Return selected open credit orders for this credit-management scope."""
    if not order_ids:
        raise CreditManagementOrderError('Selecciona al menos un pedido a crédito para pagar.')

    open_orders = get_open_credit_orders_for_credit_management(client)
    open_orders_by_id = {order.pk: order for order in open_orders}
    selected_orders = []
    for order_id in _dedupe_order_ids(order_ids):
        order = open_orders_by_id.get(order_id)
        if order is None:
            raise CreditManagementOrderError(
                f'El pedido #{order_id} no está disponible para gestionar crédito.'
            )
        selected_orders.append(order)
    return selected_orders


def get_selected_credit_orders_total(orders: Iterable[Order]) -> Decimal:
    """Return the remaining total for selected credit orders."""
    return sum(
        (payment_services.get_unpaid_amount(order) for order in orders),
        Decimal('0.00'),
    )


def _dedupe_order_ids(order_ids: list[int]) -> list[int]:
    return list(dict.fromkeys(order_ids))
