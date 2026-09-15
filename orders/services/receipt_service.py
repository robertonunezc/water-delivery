from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError

from orders.models import Order, OrderReceipt, OrderStatus
from orders.services.receipt_delivery_service import (
    ReceiptDeliveryError,
    ReceiptDeliveryService,
)
from orders.services.receipt_pdf_service import (
    ReceiptContactSnapshot,
    ReceiptPdfError,
    generate_receipt_pdf,
)
from orders.services.receipt_storage_service import ReceiptStorageError, get_receipt_storage

User = get_user_model()


class ReceiptCreationError(ValueError):
    """Raised when a receipt cannot be created for an order."""


@dataclass(frozen=True)
class ReceiptCreationResult:
    receipt: OrderReceipt
    created: bool
    delivery_succeeded: bool
    delivery_error: str


def create_signed_receipt(
    order: Order,
    cleaned_data: dict[str, Any],
    user: User,
) -> ReceiptCreationResult:
    if order.status != OrderStatus.COMPLETED.value:
        raise ReceiptCreationError("Solo se pueden firmar recibos de pedidos completados.")

    existing = getattr(order, "receipt", None)
    if existing is not None:
        return ReceiptCreationResult(
            receipt=existing,
            created=False,
            delivery_succeeded=existing.sent_at is not None,
            delivery_error="",
        )

    contact = ReceiptContactSnapshot(
        name=str(cleaned_data["contact_name"]),
        email=str(cleaned_data["contact_email"]),
        phone=str(cleaned_data.get("contact_phone") or ""),
        position=str(cleaned_data.get("contact_position") or ""),
    )
    if str(cleaned_data.get("method") or "email") == "email" and not contact.email:
        raise ReceiptCreationError("El correo de contacto es requerido para enviar el recibo.")

    try:
        pdf_bytes = generate_receipt_pdf(
            order=order,
            contact=contact,
            signature_data_url=str(cleaned_data["signature_data"]),
        )
        pdf_url = get_receipt_storage().upload_pdf(order_id=order.pk, pdf_bytes=pdf_bytes)
    except (ReceiptPdfError, ReceiptStorageError) as exc:
        raise ReceiptCreationError(str(exc)) from exc

    try:
        receipt = OrderReceipt.objects.create(
            order=order,
            method=str(cleaned_data.get("method") or "email"),
            pdf_url=pdf_url,
            contact_name=contact.name,
            contact_email=contact.email,
            contact_phone=contact.phone or None,
            contact_position=contact.position or None,
            created_by=user,
        )
    except IntegrityError:
        receipt = OrderReceipt.objects.get(order=order)
        return ReceiptCreationResult(
            receipt=receipt,
            created=False,
            delivery_succeeded=receipt.sent_at is not None,
            delivery_error="",
        )

    return _send_receipt(receipt=receipt, created=True)


def resend_receipt(receipt: OrderReceipt) -> ReceiptCreationResult:
    return _send_receipt(receipt=receipt, created=False)


def _send_receipt(receipt: OrderReceipt, created: bool) -> ReceiptCreationResult:
    try:
        sent = ReceiptDeliveryService().send(receipt)
    except ReceiptDeliveryError as exc:
        return ReceiptCreationResult(
            receipt=receipt,
            created=created,
            delivery_succeeded=False,
            delivery_error=str(exc),
        )
    return ReceiptCreationResult(
        receipt=sent,
        created=created,
        delivery_succeeded=True,
        delivery_error="",
    )
