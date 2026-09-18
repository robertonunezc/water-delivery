from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from orders.models import Order


class ReceiptPdfError(ValueError):
    """Raised when a receipt PDF cannot be generated."""


@dataclass(frozen=True)
class ReceiptContactSnapshot:
    name: str
    email: str
    phone: str = ""
    position: str = ""


def generate_receipt_pdf(
    order: Order,
    contact: ReceiptContactSnapshot | None,
    signature_data_url: str,
) -> bytes:
    signature_bytes = _decode_signature(signature_data_url)
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("PuriGest - Recibo de pedido", styles["Title"]),
        Paragraph(f"Pedido #{order.pk}", styles["Heading2"]),
        Paragraph(f"Cliente: {_safe_text(order.client.name)}", styles["Normal"]),
        Paragraph(
            f"Fecha del pedido: {timezone.localtime(order.order_date):%d/%m/%Y %H:%M}",
            styles["Normal"],
        ),
        Paragraph(
            f"Fecha del recibo: {timezone.localtime(timezone.now()):%d/%m/%Y %H:%M}",
            styles["Normal"],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Productos", styles["Heading3"]),
        _products_table(order),
        Spacer(1, 0.2 * inch),
        Paragraph("Pagos", styles["Heading3"]),
        _payments_table(order),
        Spacer(1, 0.2 * inch),
        _totals_table(order),
    ]
    if contact is not None:
        elements.extend(
            [
                Spacer(1, 0.2 * inch),
                Paragraph("Contacto", styles["Heading3"]),
                Paragraph(f"Nombre: {_safe_text(contact.name)}", styles["Normal"]),
                Paragraph(f"Correo: {_safe_text(contact.email)}", styles["Normal"]),
                Paragraph(
                    f"Telefono: {_safe_text(contact.phone or 'Sin telefono')}",
                    styles["Normal"],
                ),
                Paragraph(
                    f"Puesto: {_safe_text(contact.position or 'Sin puesto')}",
                    styles["Normal"],
                ),
            ]
        )
    elements.extend(
        [
            Spacer(1, 0.2 * inch),
            Paragraph("Firma", styles["Heading3"]),
            Image(BytesIO(signature_bytes), width=3.2 * inch, height=1.1 * inch),
        ]
    )
    document.build(elements)
    return output.getvalue()


def _decode_signature(signature_data_url: str) -> bytes:
    prefix = "data:image/png;base64,"
    if not signature_data_url.startswith(prefix):
        raise ReceiptPdfError("La firma debe enviarse como imagen PNG.")
    try:
        return base64.b64decode(signature_data_url[len(prefix):], validate=True)
    except (ValueError, TypeError) as exc:
        raise ReceiptPdfError("La firma no es valida.") from exc


def _products_table(order: Order) -> Table:
    rows = [["Producto", "Cantidad", "Precio", "Total"]]
    for item in order.items.select_related("product").all():
        rows.append(
            [
                _safe_text(item.product.get_full_name()),
                str(item.quantity),
                _money(item.unit_price),
                _money(item.get_total_price()),
            ]
        )
    if len(rows) == 1:
        rows.append(["Sin productos", "0", "$0.00", "$0.00"])
    table = Table(rows, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


def _payments_table(order: Order) -> Table:
    rows = [["Metodo", "Monto", "Fecha"]]
    for payment in order.payments.not_reversed().all():
        rows.append(
            [
                _safe_text(payment.get_method_display()),
                _money(payment.amount),
                timezone.localtime(payment.date).strftime("%d/%m/%Y %H:%M"),
            ]
        )
    if len(rows) == 1:
        rows.append(["Sin pagos", "$0.00", ""])
    table = Table(rows, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


def _totals_table(order: Order) -> Table:
    rows = [
        ["Subtotal", _money(order.subtotal_amount)],
        ["Descuento", _money(order.discount)],
        ["Total", _money(order.total_amount)],
    ]
    if order.cantidad_cobrada is not None:
        rows.append(["Cantidad cobrada", _money(order.cantidad_cobrada)])
    table = Table(rows, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]
    )


def _money(value: Decimal | int | float | None) -> str:
    return f"${Decimal(str(value or 0)):.2f}"


def _safe_text(value: object) -> str:
    return escape(str(value or ""))
