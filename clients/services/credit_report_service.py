from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from clients.models import Client, ClientCreditConfig
from clients.services.pending_payment_service import (
    get_order_credit_due_date,
    is_order_overdue,
)
from invoice.models import Invoice, InvoiceStatus
from orders.models import Order


ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CreditOrderReportItem:
    order: Order
    invoice: Invoice | None
    total_amount: Decimal
    paid_amount: Decimal
    remaining_amount: Decimal
    due_date: date | None
    days_overdue: int
    is_overdue: bool


@dataclass(frozen=True)
class CreditInvoiceReportItem:
    invoice: Invoice
    orders: list[CreditOrderReportItem]
    open_amount: Decimal
    overdue_amount: Decimal
    due_date: date | None
    is_overdue: bool
    status: str


@dataclass(frozen=True)
class ClientCreditReport:
    client: Client
    current_credit: Decimal
    authorized_credit_line: Decimal
    available_credit: Decimal
    overdue_amount: Decimal
    open_credit_total: Decimal
    invoiced_credit_total: Decimal
    uninvoiced_credit_total: Decimal
    invoice_items: list[CreditInvoiceReportItem]
    uninvoiced_orders: list[CreditOrderReportItem]
    reconciliation_difference: Decimal
    has_reconciliation_warning: bool


@dataclass(frozen=True)
class GlobalCreditReportRow:
    client: Client
    current_credit: Decimal
    authorized_credit_line: Decimal
    available_credit: Decimal
    overdue_amount: Decimal


@dataclass(frozen=True)
class GlobalCreditReport:
    rows: list[GlobalCreditReportRow]
    total_current_credit: Decimal
    total_authorized_credit_line: Decimal
    total_available_credit: Decimal
    total_overdue_amount: Decimal


def _today() -> date:
    return timezone.localdate()


def _money(value: Decimal | int | float | None) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _get_credit_order_ids_for_clients(client_ids: list[int]) -> list[int]:
    return list(
        Order.objects.all().for_credit_accounts(client_ids).values_list('pk', flat=True)
    )


def _get_credit_client_ids_by_order_id(client_ids: list[int]) -> dict[int, int]:
    rows = Order.objects.all().for_credit_accounts(client_ids).values_list('pk', 'resolved_credit_account_id')
    return dict(rows)


def _get_open_credit_orders_for_client(client: Client) -> list[Order]:
    credit_account = client.get_credit_account()
    orders = Order.objects.active().unpaid().for_credit_accounts([credit_account.pk])
    if credit_account.pk != client.pk:
        orders = orders.filter(client=client)
    return list(
        orders
        .select_related("client", "client__credit_config", "client__corporate")
        .prefetch_related("invoice_links__invoice", "payments")
        .order_by("order_date", "id")
    )


def _get_open_credit_orders_for_clients(client_ids: list[int]) -> list[Order]:
    if not client_ids:
        return []

    credit_order_ids = _get_credit_order_ids_for_clients(client_ids)
    if not credit_order_ids:
        return []

    return list(
        Order.objects.active()
        .unpaid()
        .filter(pk__in=credit_order_ids)
        .select_related("client", "client__credit_config", "client__corporate")
        .prefetch_related("invoice_links__invoice", "payments")
        .order_by("order_date", "id")
    )


def _get_order_invoice(order: Order) -> Invoice | None:
    return next(
        (
            link.invoice
            for link in order.invoice_links.all()
            if link.invoice.status == InvoiceStatus.ACTIVE
        ),
        None,
    )


def _get_credit_config(client: Client) -> ClientCreditConfig | None:
    try:
        return client.credit_config
    except ClientCreditConfig.DoesNotExist:
        return None


def _get_order_due_date(order: Order) -> date | None:
    credit_config = order.get_effective_credit_config()
    if credit_config is None:
        return None
    return get_order_credit_due_date(order, credit_config)


def _get_order_paid_amount(order: Order) -> Decimal:
    return _money(getattr(order, "total_paid", ZERO))


def _build_order_item(order: Order, *, as_of: date) -> CreditOrderReportItem:
    paid_amount = _get_order_paid_amount(order)
    total_amount = _money(order.total_amount)
    remaining_amount = max(total_amount - paid_amount, ZERO)
    due_date = _get_order_due_date(order)
    is_overdue = bool(
        due_date
        and is_order_overdue(as_of, due_date)
        and remaining_amount > ZERO
    )
    days_overdue = (as_of - due_date).days if due_date and is_overdue else 0
    return CreditOrderReportItem(
        order=order,
        invoice=_get_order_invoice(order),
        total_amount=total_amount,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        due_date=due_date,
        days_overdue=days_overdue,
        is_overdue=is_overdue,
    )


def _build_invoice_item(
    invoice: Invoice,
    orders: list[CreditOrderReportItem],
) -> CreditInvoiceReportItem:
    due_dates = [item.due_date for item in orders if item.due_date is not None]
    overdue_amount = sum(
        (item.remaining_amount for item in orders if item.is_overdue),
        ZERO,
    )
    is_overdue = overdue_amount > ZERO
    return CreditInvoiceReportItem(
        invoice=invoice,
        orders=orders,
        open_amount=sum((item.remaining_amount for item in orders), ZERO),
        overdue_amount=overdue_amount,
        due_date=min(due_dates) if due_dates else None,
        is_overdue=is_overdue,
        status="Vencida" if is_overdue else "En plazo",
    )


def _group_items_by_invoice(
    items: list[CreditOrderReportItem],
) -> tuple[list[CreditInvoiceReportItem], list[CreditOrderReportItem]]:
    invoice_groups: dict[int, list[CreditOrderReportItem]] = {}
    invoices_by_id: dict[int, Invoice] = {}
    uninvoiced_orders = []

    for item in items:
        if item.invoice is None:
            uninvoiced_orders.append(item)
            continue
        invoice_groups.setdefault(item.invoice.pk, []).append(item)
        invoices_by_id[item.invoice.pk] = item.invoice

    invoice_items = [
        _build_invoice_item(invoices_by_id[invoice_id], orders)
        for invoice_id, orders in invoice_groups.items()
    ]
    invoice_items.sort(
        key=lambda item: (
            item.due_date or date.max,
            item.invoice.emmited_at or date.max,
            item.invoice.identifier,
            item.invoice.folio,
        )
    )
    return invoice_items, uninvoiced_orders


def _build_client_report_from_orders(
    client: Client,
    orders: list[Order],
    *,
    as_of: date,
) -> ClientCreditReport:
    order_items = [_build_order_item(order, as_of=as_of) for order in orders]
    invoice_items, uninvoiced_orders = _group_items_by_invoice(order_items)
    open_credit_total = sum((item.remaining_amount for item in order_items), ZERO)
    overdue_amount = sum(
        (item.remaining_amount for item in order_items if item.is_overdue),
        ZERO,
    )
    credit_account = client.get_credit_account()
    current_credit = _money(credit_account.current_debt)
    authorized_credit_line = _money(credit_account.credit_limit)
    reconciliation_difference = current_credit - open_credit_total
    return ClientCreditReport(
        client=client,
        current_credit=current_credit,
        authorized_credit_line=authorized_credit_line,
        available_credit=authorized_credit_line - current_credit,
        overdue_amount=overdue_amount,
        open_credit_total=open_credit_total,
        invoiced_credit_total=sum(
            (item.open_amount for item in invoice_items),
            ZERO,
        ),
        uninvoiced_credit_total=sum(
            (item.remaining_amount for item in uninvoiced_orders),
            ZERO,
        ),
        invoice_items=invoice_items,
        uninvoiced_orders=uninvoiced_orders,
        reconciliation_difference=reconciliation_difference,
        has_reconciliation_warning=reconciliation_difference != ZERO,
    )


def get_client_credit_report(
    *,
    client: Client,
    as_of: date | None = None,
) -> ClientCreditReport:
    """Build the detailed credit report for a single client."""
    report_date = as_of or _today()
    orders = _get_open_credit_orders_for_client(client)
    return _build_client_report_from_orders(client, orders, as_of=report_date)


def get_credit_report_order_ids(client: Client) -> list[int]:
    """Return the open orders shown in this client's credit report."""
    return [order.pk for order in _get_open_credit_orders_for_client(client)]


@transaction.atomic
def pay_credit_report_orders(
    *, client: Client, order_ids: list[int], payment_method: str,
    amount: Decimal, request_user: Any, payment_date: date,
) -> dict[str, object]:
    """Recheck the report's credit scope under locks before settling orders."""
    from orders.services.credit_lock_service import lock_order_credit_clients
    from payment import services as payment_services

    lock_order_credit_clients(order_ids, extra_client_ids=[client.pk])
    client.refresh_from_db()
    list(Order.objects.select_for_update().filter(pk__in=order_ids).order_by('pk'))
    allowed_ids = get_credit_report_order_ids(client)
    orders = payment_services.get_selected_unpaid_orders(
        client, order_ids, allowed_order_ids=allowed_ids,
    )
    return payment_services.pay_client_orders(
        client=client, orders=orders, payment_method=payment_method,
        amount=amount, request_user=request_user, payment_date=payment_date,
        allowed_order_ids=allowed_ids,
        payment_client=client if payment_method == 'balance' else None,
    )


def get_global_credit_report(*, as_of: date | None = None) -> GlobalCreditReport:
    """Build credit rows for active clients with a credit line or current debt."""
    report_date = as_of or _today()
    clients = list(
        Client.objects.filter(active=True)
        .filter(Q(credit_limit__gt=0) | Q(current_debt__gt=0))
        .exclude(
            type="branch",
            corporate_id__isnull=False,
            credit_override_enabled=False,
        )
        .select_related("credit_config", "corporate")
        .order_by("name")
    )
    client_ids = [client.pk for client in clients]
    orders = _get_open_credit_orders_for_clients(client_ids)
    credit_client_ids_by_order_id = _get_credit_client_ids_by_order_id(client_ids)
    orders_by_client: dict[int, list[Order]] = {}
    for order in orders:
        credit_client_id = credit_client_ids_by_order_id.get(order.pk, order.client_id)
        orders_by_client.setdefault(credit_client_id, []).append(order)

    rows = []
    for client in clients:
        report = _build_client_report_from_orders(
            client,
            orders_by_client.get(client.pk, []),
            as_of=report_date,
        )
        rows.append(
            GlobalCreditReportRow(
                client=client,
                current_credit=report.current_credit,
                authorized_credit_line=report.authorized_credit_line,
                available_credit=report.available_credit,
                overdue_amount=report.overdue_amount,
            )
        )

    rows.sort(
        key=lambda row: (
            -row.overdue_amount,
            -row.current_credit,
            row.client.name.lower(),
        )
    )
    return GlobalCreditReport(
        rows=rows,
        total_current_credit=sum((row.current_credit for row in rows), ZERO),
        total_authorized_credit_line=sum(
            (row.authorized_credit_line for row in rows),
            ZERO,
        ),
        total_available_credit=sum((row.available_credit for row in rows), ZERO),
        total_overdue_amount=sum((row.overdue_amount for row in rows), ZERO),
    )
