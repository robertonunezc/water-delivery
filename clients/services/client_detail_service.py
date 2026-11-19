from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from django.db.models import QuerySet

from clients.models import Client
from clients.services.client_debt_service import get_client_display_current_debt

ZERO = Decimal("0.00")


def _money(value: Any) -> str:
    return f"${float(value):.2f}"


def get_client_detail_current_debt(client: Client) -> Decimal:
    """Return the debt amount shown on the client detail page."""
    return get_client_display_current_debt(client)


def _pending_invoice_count(client_invoices: Sequence[Any]) -> int:
    return sum(
        1
        for invoice in client_invoices
        if (
            getattr(invoice, 'status', 'ACTIVE') == 'ACTIVE'
            and getattr(invoice, "pending_amount", 0) > 0
        )
    )


def _pending_invoice_note(pending_count: int) -> str:
    if pending_count == 1:
        return "1 factura pendiente"
    return f"{pending_count} facturas pendientes"


def _next_billing_summary(
    *,
    client: Client,
    billing_frequency: Any,
    client_invoices: Sequence[Any],
) -> tuple[str, str, str]:
    pending_count = _pending_invoice_count(client_invoices)
    pending_note = _pending_invoice_note(pending_count)

    if not client.requires_billing:
        return "No aplica", "Cliente sin facturación recurrente", "muted"

    if billing_frequency and billing_frequency.next_billing_date:
        tone = "warning" if pending_count > 0 else "primary"
        return (
            f"Próxima: {billing_frequency.next_billing_date:%d/%m/%Y}",
            pending_note,
            tone,
        )

    tone = "warning" if pending_count > 0 else "muted"
    return "Sin fecha", pending_note, tone


DEFAULT_DETAIL_TAB = "orders"
DETAIL_TABS = ("orders", "movements", "invoices", "deliveries", "data")
LEGACY_DETAIL_TAB_ALIASES = {
    "sales": "orders",
    "payments": "movements",
    "routes": "deliveries",
    "profile": "data",
    "prices": "data",
}
ORDER_FILTERS = ("all", "due", "overdue")
MOVEMENT_TYPES = ("all", "payment", "balance_transaction", "credit_transaction")


def resolve_client_detail_tab(requested_tab: str | None) -> str:
    """Map a requested tab (including legacy names) to a valid detail tab."""
    tab = LEGACY_DETAIL_TAB_ALIASES.get(requested_tab or "", requested_tab)
    return tab if tab in DETAIL_TABS else DEFAULT_DETAIL_TAB


def resolve_choice(requested: str | None, choices: Sequence[str]) -> str:
    """Return the requested value when allowed, otherwise the first choice."""
    return requested if requested in choices else choices[0]


def filter_client_detail_orders(
    orders: QuerySet,
    order_filter: str,
    overdue_order_ids: Sequence[int],
) -> QuerySet:
    """Narrow the client order list for the Pedidos tab filter chips."""
    if order_filter == "due":
        return orders.active().unpaid()
    if order_filter == "overdue":
        return orders.filter(pk__in=list(overdue_order_ids))
    return orders


def filter_client_detail_movements(
    movements: Sequence[dict[str, Any]],
    movement_type: str,
) -> list[dict[str, Any]]:
    """Narrow the unified ledger for the Movimientos tab filter chips."""
    if movement_type == "all":
        return list(movements)
    return [item for item in movements if item.get("type") == movement_type]


def build_overdue_payment_query(overdue_orders: Sequence[Any]) -> str:
    """Build the querystring that preselects overdue orders for payment."""
    return urlencode([("orders", order.pk) for order in overdue_orders])


def _credit_bar_tone(has_financial_risk: bool, debt_percentage: int) -> str:
    if has_financial_risk:
        return "danger"
    if debt_percentage > 60:
        return "warning"
    return "success"


def build_client_detail_snapshot(
    *,
    client: Client,
    billing_frequency: Any,
    client_invoices: Sequence[Any],
    pending_payment_data: dict[str, Any],
    debt_percentage: int,
) -> dict[str, Any]:
    has_financial_risk = pending_payment_data.get("total_overdue_amount", 0) > 0
    current_debt = get_client_detail_current_debt(client)
    credit_account = client.get_credit_account()
    billing_value, billing_note, billing_tone = _next_billing_summary(
        client=client,
        billing_frequency=billing_frequency,
        client_invoices=client_invoices,
    )
    credit_enabled = credit_account.credit_limit > 0
    credit_value = f"{debt_percentage}%" if credit_enabled else "Sin crédito"
    credit_note = (
        f"Disponible: {_money(client.get_available_credit())} de {_money(credit_account.credit_limit)}"
        if credit_enabled
        else "Sin crédito habilitado"
    )

    return {
        "has_financial_risk": has_financial_risk,
        "has_current_debt": current_debt > 0,
        "credit_enabled": credit_enabled,
        "credit_usage_percent": min(max(debt_percentage, 0), 100),
        "credit_bar_tone": _credit_bar_tone(has_financial_risk, debt_percentage),
        "overdue_payment_query": build_overdue_payment_query(
            pending_payment_data.get("overdue_orders", []),
        ),
        "credit_report_url_label": "Ver reporte de crédito",
        "snapshot_cards": [
            {
                "label": "Saldo prepago",
                "value": _money(client.balance),
                "note": "Disponible" if client.balance > 0 else "Sin saldo",
                "tone": "success" if client.balance > 0 else "muted",
            },
            {
                "label": "Deuda actual",
                "value": _money(current_debt),
                "note": (
                    "Vencida"
                    if has_financial_risk
                    else ("Pendiente" if current_debt > 0 else "Sin deuda")
                ),
                "tone": (
                    "danger"
                    if has_financial_risk or current_debt > 0
                    else "success"
                ),
            },
            {
                "label": "Crédito",
                "value": credit_value,
                "note": credit_note,
                "tone": "warning" if debt_percentage > 60 else "success",
            },
            {
                "label": "Facturación",
                "value": billing_value,
                "note": billing_note,
                "tone": billing_tone,
            },
        ],
    }
