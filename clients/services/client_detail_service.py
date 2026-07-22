from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db.models.query import QuerySet

from clients.models import Client


def _money(value: Any) -> str:
    return f"${float(value):.2f}"


def _next_visit_summary(
    *,
    route_clients: QuerySet[Any],
    upcoming_route_orders: Sequence[Any],
) -> tuple[str, str]:
    if upcoming_route_orders:
        route_order = upcoming_route_orders[0]
        return (
            route_order.visit_date.strftime("%d/%m"),
            f"{route_order.route.name} - Secuencia {route_order.sequence}",
        )

    route_client = route_clients.first()
    if route_client:
        return (
            route_client.route.get_weekday_display(),
            f"{route_client.route.name} - Secuencia {route_client.sequence}",
        )

    return "Sin ruta", "Sin ruta asignada"


def _pending_invoice_count(client_invoices: Sequence[Any]) -> int:
    return sum(
        1
        for invoice in client_invoices
        if getattr(invoice, "pending_amount", 0) > 0
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


def build_client_detail_snapshot(
    *,
    client: Client,
    billing_frequency: Any,
    route_clients: QuerySet[Any],
    upcoming_route_orders: Sequence[Any],
    client_invoices: Sequence[Any],
    pending_payment_data: dict[str, Any],
    debt_percentage: int,
) -> dict[str, Any]:
    has_financial_risk = pending_payment_data.get("total_overdue_amount", 0) > 0
    visit_value, visit_note = _next_visit_summary(
        route_clients=route_clients,
        upcoming_route_orders=upcoming_route_orders,
    )
    billing_value, billing_note, billing_tone = _next_billing_summary(
        client=client,
        billing_frequency=billing_frequency,
        client_invoices=client_invoices,
    )
    credit_enabled = client.credit_limit > 0
    credit_value = f"{debt_percentage}%" if credit_enabled else "Sin crédito"
    credit_note = (
        f"Disponible: {_money(client.get_available_credit())} de {_money(client.credit_limit)}"
        if credit_enabled
        else "Sin crédito habilitado"
    )

    return {
        "has_financial_risk": has_financial_risk,
        "credit_report_url_label": "Ver reporte de crédito",
        "snapshot_cards": [
            {
                "label": "Saldo prepago",
                "value": _money(client.balance),
                "note": "Disponible" if client.balance > 0 else "Sin saldo",
                "tone": "success" if client.balance > 0 else "muted",
                "action_label": "Gestionar saldo",
                "action_url_name": "clients:add_balance",
                "action_icon": "fas fa-wallet",
            },
            {
                "label": "Deuda actual",
                "value": _money(client.current_debt),
                "note": (
                    "Vencida"
                    if has_financial_risk
                    else ("Pendiente" if client.current_debt > 0 else "Sin deuda")
                ),
                "tone": (
                    "danger"
                    if has_financial_risk or client.current_debt > 0
                    else "success"
                ),
            },
            {
                "label": "Crédito",
                "value": credit_value,
                "note": credit_note,
                "tone": "warning" if debt_percentage > 60 else "success",
                "action_label": "Gestionar crédito",
                "action_url_name": "clients:pay_credit",
                "action_icon": "fas fa-credit-card",
            },
            {
                "label": "Próxima visita",
                "value": visit_value,
                "note": visit_note,
                "tone": "primary" if visit_note != "Sin ruta asignada" else "muted",
            },
            {
                "label": "Facturación",
                "value": billing_value,
                "note": billing_note,
                "tone": billing_tone,
            },
        ],
    }
