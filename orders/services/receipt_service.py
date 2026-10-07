from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection

from orders.models import Order, OrderReceipt, OrderStatus, ReceiptDeliveryMethod
from orders.services.receipt_delivery_service import (
    ReceiptDeliveryError,
    ReceiptDeliveryService,
    normalize_whatsapp_phone,
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
    delivery_url: str = ""


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
    method = _resolve_receipt_delivery_method(order.client, contact)
    if not method:
        raise ReceiptCreationError(
            "El contacto requiere correo electrónico o teléfono para enviar el recibo."
        )

    try:
        pdf_bytes = generate_receipt_pdf(
            order=order,
            contact=contact,
            signature_data_url=str(cleaned_data["signature_data"]),
        )
        pdf_url = get_receipt_storage().upload_pdf(
            tenant_id=connection.tenant.pk,
            client_id=order.client_id,
            order_id=order.pk,
            pdf_bytes=pdf_bytes,
        )
    except (ReceiptPdfError, ReceiptStorageError) as exc:
        raise ReceiptCreationError(str(exc)) from exc

    try:
        receipt = OrderReceipt.objects.create(
            order=order,
            method=method,
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


def create_signature_only_receipt(
    order: Order,
    signature_data: str,
    user: User,
) -> ReceiptCreationResult:
    if order.status != OrderStatus.COMPLETED.value:
        raise ReceiptCreationError("Solo se pueden firmar recibos de pedidos completados.")

    existing = getattr(order, "receipt", None)
    if existing is not None:
        return ReceiptCreationResult(
            receipt=existing,
            created=False,
            delivery_succeeded=False,
            delivery_error="",
        )

    try:
        pdf_bytes = generate_receipt_pdf(
            order=order,
            contact=None,
            signature_data_url=signature_data,
        )
        pdf_url = get_receipt_storage().upload_pdf(
            tenant_id=connection.tenant.pk,
            client_id=order.client_id,
            order_id=order.pk,
            pdf_bytes=pdf_bytes,
        )
    except (ReceiptPdfError, ReceiptStorageError) as exc:
        raise ReceiptCreationError(str(exc)) from exc

    try:
        receipt = OrderReceipt.objects.create(
            order=order,
            method=ReceiptDeliveryMethod.NONE,
            pdf_url=pdf_url,
            contact_name="",
            contact_email="",
            created_by=user,
        )
    except IntegrityError:
        receipt = OrderReceipt.objects.get(order=order)
        return ReceiptCreationResult(
            receipt=receipt,
            created=False,
            delivery_succeeded=False,
            delivery_error="",
        )

    return ReceiptCreationResult(
        receipt=receipt,
        created=True,
        delivery_succeeded=False,
        delivery_error="",
    )


def resend_receipt(receipt: OrderReceipt) -> ReceiptCreationResult:
    if receipt.method == ReceiptDeliveryMethod.NONE:
        return ReceiptCreationResult(
            receipt=receipt,
            created=False,
            delivery_succeeded=False,
            delivery_error="",
        )
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
        receipt=sent.receipt,
        created=created,
        delivery_succeeded=True,
        delivery_error="",
        delivery_url=sent.delivery_url,
    )


def _resolve_receipt_delivery_method(
    client: Any,
    contact: ReceiptContactSnapshot,
) -> str:
    for method in _receipt_delivery_method_order(client):
        if method == ReceiptDeliveryMethod.WHATSAPP and normalize_whatsapp_phone(
            contact.phone
        ):
            return ReceiptDeliveryMethod.WHATSAPP
        if method == ReceiptDeliveryMethod.EMAIL and contact.email:
            return ReceiptDeliveryMethod.EMAIL
    return ""


def _receipt_delivery_method_order(client: Any) -> tuple[str, str]:
    preferred_method = getattr(
        client,
        "confirmation_delivery_method",
        ReceiptDeliveryMethod.WHATSAPP,
    )
    if preferred_method not in {
        ReceiptDeliveryMethod.EMAIL,
        ReceiptDeliveryMethod.WHATSAPP,
    }:
        preferred_method = ReceiptDeliveryMethod.WHATSAPP
    fallback_method = (
        ReceiptDeliveryMethod.EMAIL
        if preferred_method == ReceiptDeliveryMethod.WHATSAPP
        else ReceiptDeliveryMethod.WHATSAPP
    )
    return preferred_method, fallback_method
