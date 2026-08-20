from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from clients.models import Client

ZERO = Decimal("0.00")


def _money(value: Any) -> str:
    return f"${float(value):.2f}"


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or ZERO))


def _get_inherited_branch_debt(client: Client, credit_account: Client) -> Decimal:
    summary = (
        credit_account.credit_transactions.filter(reference_order__client=client)
        .aggregate_summary()
    )
    debt = summary["total_purchases"] - summary["total_payments"]
    return max(debt, ZERO)


def get_client_detail_current_debt(client: Client) -> Decimal:
    """Return the debt amount shown on the client detail page."""
    credit_account = client.get_credit_account()
    if credit_account.pk == client.pk:
        return _decimal(client.current_debt)
    return _get_inherited_branch_debt(client, credit_account)


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
                "action_label": "Pago de deuda",
                "action_url_name": "clients:pay_credit",
                "action_icon": "fas fa-credit-card",
            },
            {
                "label": "Facturación",
                "value": billing_value,
                "note": billing_note,
                "tone": billing_tone,
            },
        ],
    }
