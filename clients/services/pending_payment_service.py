from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Max
from django.utils import timezone

from clients.models import Client, ClientCreditConfig, CreditTransaction
from orders.models import Order


def _as_date(value: date | datetime) -> date:
    """Normalize date-like values for projects with or without timezone support."""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    return value


def _current_date() -> date:
    """Return today's date without assuming timezone-aware datetimes."""
    return _as_date(timezone.now())


def _monthly_cutoff_date(reference_date: date, cutoff_day: str) -> date:
    last_day = monthrange(reference_date.year, reference_date.month)[1]
    day = last_day if cutoff_day == 'last_day' else min(int(cutoff_day), last_day)
    cutoff_date = reference_date.replace(day=day)
    if reference_date <= cutoff_date:
        return cutoff_date

    next_month = (reference_date.replace(day=1) + timedelta(days=32)).replace(day=1)
    next_last_day = monthrange(next_month.year, next_month.month)[1]
    next_day = next_last_day if cutoff_day == 'last_day' else min(int(cutoff_day), next_last_day)
    return next_month.replace(day=next_day)


def get_order_credit_due_date(
    order: Order,
    credit_config: ClientCreditConfig,
) -> date | None:
    """Return the payment due date for an order under the client's credit terms."""
    if credit_config.payment_term_type == 'monthly_cutoff':
        order_date = _as_date(order.order_date)
        return _monthly_cutoff_date(order_date, credit_config.cutoff_day)

    emitted_dates = [
        link.invoice.emmited_at
        for link in order.invoice_links.all()
        if link.invoice and link.invoice.emmited_at
    ]
    if not emitted_dates:
        return None
    return min(emitted_dates) + timedelta(days=credit_config.max_payment_days)


def _overdue_order_data(
    client: Client,
    orders: list[Order],
    current_date: date,
) -> tuple[list[Order], Decimal, int]:
    overdue_orders = []
    total_overdue = Decimal('0.00')
    maximum_days_overdue = 0

    for order in orders:
        credit_config = order.client.get_effective_credit_config()
        if credit_config is None:
            continue

        due_date = get_order_credit_due_date(order, credit_config)
        if due_date is None or current_date <= due_date:
            continue

        days_overdue = (current_date - due_date).days
        remaining_amount = max(
            order.total_amount - getattr(order, 'total_paid', Decimal('0.00')),
            Decimal('0.00'),
        )
        order.days_overdue = days_overdue
        order.remaining_amount = remaining_amount
        order.credit_due_date = due_date
        overdue_orders.append(order)
        total_overdue += remaining_amount
        maximum_days_overdue = max(maximum_days_overdue, days_overdue)

    overdue_orders.sort(key=lambda order: order.days_overdue, reverse=True)
    return overdue_orders, total_overdue, maximum_days_overdue


def get_overdue_orders_for_client(client: Client) -> dict[str, Any]:
    """Return due-date and overdue information for outstanding credit orders."""
    credit_account = client.get_credit_account()
    credit_transactions = CreditTransaction.objects.filter(
        client=credit_account,
        transaction_type='purchase',
        reference_order__isnull=False,
    )
    if credit_account.pk != client.pk:
        credit_transactions = credit_transactions.filter(reference_order__client=client)

    credit_order_ids = credit_transactions.values('reference_order_id')
    unpaid_orders = list(
        Order.objects.active().unpaid()
        .filter(pk__in=credit_order_ids)
        .select_related('client', 'client__credit_config', 'client__corporate')
        .prefetch_related('invoice_links__invoice')
    )
    current_date = _current_date()
    overdue_orders, total_overdue, days_overdue = _overdue_order_data(
        client,
        unpaid_orders,
        current_date,
    )
    due_dates = [
        due_date
        for order in unpaid_orders
        for credit_config in [order.client.get_effective_credit_config()]
        if credit_config
        for due_date in [get_order_credit_due_date(order, credit_config)]
        if due_date is not None
    ]
    nearest_due_date = min(due_dates, default=None)
    awaiting_invoice = any(
        credit_config
        and credit_config.payment_term_type == 'invoice_due'
        and get_order_credit_due_date(order, credit_config) is None
        for order in unpaid_orders
        for credit_config in [order.client.get_effective_credit_config()]
    )
    return {
        'total_overdue_amount': total_overdue,
        'days_overdue': days_overdue,
        'overdue_orders': overdue_orders,
        'nearest_due_date': nearest_due_date,
        'nearest_due_is_overdue': bool(
            nearest_due_date and nearest_due_date < current_date
        ),
        'awaiting_invoice': awaiting_invoice,
    }


def client_has_overdue_credit(client: Client) -> bool:
    """Return whether the client has debt past its configured payment date."""
    return bool(get_overdue_orders_for_client(client)['overdue_orders'])


def get_clients_with_pending_payments() -> list[dict[str, Any]]:
    """Return active clients that have overdue credit orders."""
    clients = list(
        Client.objects.filter(active=True).select_related(
            'credit_config',
            'corporate',
            'corporate__credit_config',
        )
    )
    clients_map = {client.id: client for client in clients}
    credit_order_ids = CreditTransaction.objects.filter(
        transaction_type='purchase',
        reference_order__isnull=False,
        reference_order__client_id__in=clients_map,
    ).values('reference_order_id')
    unpaid_orders = (
        Order.objects.active().unpaid()
        .filter(client_id__in=clients_map, pk__in=credit_order_ids)
        .select_related('client', 'client__credit_config', 'client__corporate')
        .prefetch_related('invoice_links__invoice')
    )
    orders_by_client: dict[int, list[Order]] = {}
    for order in unpaid_orders:
        orders_by_client.setdefault(order.client_id, []).append(order)

    last_payments = CreditTransaction.objects.filter(
        transaction_type='payment',
        reference_order__client_id__in=clients_map,
    ).values('reference_order__client_id').annotate(last_date=Max('created_at'))
    last_payment_map = {
        item['reference_order__client_id']: item['last_date']
        for item in last_payments
    }

    clients_data = []
    current_date = _current_date()
    for client_id, orders in orders_by_client.items():
        overdue_orders, total_overdue, days_overdue = _overdue_order_data(
            clients_map[client_id],
            orders,
            current_date,
        )
        if not overdue_orders:
            continue
        clients_data.append({
            'client': clients_map[client_id],
            'total_overdue_amount': total_overdue,
            'days_overdue': days_overdue,
            'missing_payment_orders': overdue_orders,
            'last_payment_date': last_payment_map.get(client_id),
        })

    clients_data.sort(key=lambda item: item['total_overdue_amount'], reverse=True)
    return clients_data
