from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from notification.channels.email import EmailAttachment, SendEmail
from orders.models import Order, OrderReceipt, ReceiptDeliveryMethod
from orders.services.receipt_storage_service import get_receipt_storage


class ReceiptDeliveryError(RuntimeError):
    """Raised when a receipt cannot be delivered."""


@dataclass(frozen=True)
class ReceiptBundleDeliveryResult:
    attached_order_ids: tuple[int, ...]
    missing_order_ids: tuple[int, ...]


@dataclass(frozen=True)
class ReceiptDeliveryOutcome:
    delivery_url: str = ""


@dataclass(frozen=True)
class ReceiptDeliveryResult:
    receipt: OrderReceipt
    delivery_url: str = ""


class ReceiptSender(Protocol):
    def send(self, receipt: OrderReceipt) -> ReceiptDeliveryOutcome:
        ...


class EmailReceiptSender:
    def send(self, receipt: OrderReceipt) -> ReceiptDeliveryOutcome:
        pdf_bytes = get_receipt_storage().download_pdf(receipt.pdf_url)
        attachment = EmailAttachment(
            filename=f"recibo-pedido-{receipt.order_id}.pdf",
            content=pdf_bytes,
            content_type="application/pdf",
        )
        sender = SendEmail(
            to=receipt.contact_email,
            from_=getattr(
                settings,
                "RECEIPT_EMAIL_FROM",
                "WaterDelivery<soporte@puntoreica.com>",
            ),
            subject=f"Recibo firmado pedido #{receipt.order_id}",
            body=(
                f"Adjuntamos el recibo firmado del pedido #{receipt.order_id}.\n\n"
                "Gracias."
            ),
            attachments=[attachment],
        )
        sender.send_email()
        return ReceiptDeliveryOutcome()


class WhatsAppReceiptSender:
    def send(self, receipt: OrderReceipt) -> ReceiptDeliveryOutcome:
        phone = normalize_whatsapp_phone(receipt.contact_phone or "")
        if not phone:
            raise ReceiptDeliveryError("El teléfono de contacto no es válido.")

        signed_url = get_receipt_storage().generate_signed_url(receipt.pdf_url)
        greeting = f"Hola {receipt.contact_name}," if receipt.contact_name else "Hola,"
        body = (
            f"{greeting}\n\n"
            f"Te compartimos el recibo firmado del pedido #{receipt.order_id}:\n"
            f"{signed_url}\n\n"
            "El enlace estará disponible por 24 horas."
        )
        return ReceiptDeliveryOutcome(
            delivery_url=build_whatsapp_url(phone, body),
        )


class ReceiptSenderFactory:
    def __init__(self) -> None:
        self._senders: dict[str, ReceiptSender] = {
            ReceiptDeliveryMethod.EMAIL: EmailReceiptSender(),
            ReceiptDeliveryMethod.WHATSAPP: WhatsAppReceiptSender(),
        }

    def get_sender(self, method: str) -> ReceiptSender:
        sender = self._senders.get(method)
        if sender is None:
            raise ReceiptDeliveryError(f"Metodo de envio no soportado: {method}")
        return sender


class ReceiptDeliveryService:
    def __init__(self, factory: ReceiptSenderFactory | None = None) -> None:
        self.factory = factory or ReceiptSenderFactory()

    def send(self, receipt: OrderReceipt) -> ReceiptDeliveryResult:
        try:
            outcome = self.factory.get_sender(receipt.method).send(receipt)
        except Exception as exc:
            raise ReceiptDeliveryError(str(exc)) from exc

        receipt.sent_at = timezone.now()
        receipt.save(update_fields=["sent_at", "updated_at"])
        return ReceiptDeliveryResult(
            receipt=receipt,
            delivery_url=outcome.delivery_url,
        )


def normalize_whatsapp_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) < 10:
        return ""
    if len(digits) == 10:
        return f"52{digits}"
    return digits


def build_whatsapp_url(phone: str, message: str) -> str:
    encoded_message = quote(message.strip(), safe="")
    return f"https://wa.me/{phone}?text={encoded_message}"


class ReceiptBundleDeliveryService:
    def send(
        self,
        *,
        orders: list[Order],
        recipient_name: str,
        recipient_email: str,
    ) -> ReceiptBundleDeliveryResult:
        try:
            attachments, attached_ids, missing_ids = self._build_attachments(orders)
            if not attachments:
                raise ReceiptDeliveryError("No hay recibos firmados para enviar.")

            SendEmail(
                to=recipient_email,
                from_=getattr(
                    settings,
                    "RECEIPT_EMAIL_FROM",
                    "WaterDelivery<soporte@puntoreica.com>",
                ),
                subject=self._subject(orders),
                body=self._body(recipient_name, attached_ids),
                attachments=attachments,
            ).send_email()
        except ReceiptDeliveryError:
            raise
        except Exception as exc:
            raise ReceiptDeliveryError(str(exc)) from exc

        return ReceiptBundleDeliveryResult(
            attached_order_ids=tuple(attached_ids),
            missing_order_ids=tuple(missing_ids),
        )

    def _build_attachments(
        self,
        orders: list[Order],
    ) -> tuple[list[EmailAttachment], list[int], list[int]]:
        attachments = []
        attached_ids = []
        missing_ids = []
        storage = None

        for order in orders:
            receipt = getattr(order, "receipt", None)
            if receipt is None or receipt.deleted_at is not None:
                missing_ids.append(order.pk)
                continue

            if storage is None:
                storage = get_receipt_storage()
            attachments.append(
                EmailAttachment(
                    filename=f"recibo-pedido-{order.pk}.pdf",
                    content=storage.download_pdf(receipt.pdf_url),
                    content_type="application/pdf",
                )
            )
            attached_ids.append(order.pk)

        return attachments, attached_ids, missing_ids

    @staticmethod
    def _subject(orders: list[Order]) -> str:
        client_name = orders[0].client.name if orders else "cliente"
        return f"Recibos firmados - {client_name}"

    @staticmethod
    def _body(recipient_name: str, order_ids: list[int]) -> str:
        greeting = f"Hola {recipient_name},\n\n" if recipient_name else "Hola,\n\n"
        order_list = ", ".join(f"#{order_id}" for order_id in order_ids)
        return (
            f"{greeting}Adjuntamos los recibos firmados de los pedidos "
            f"{order_list}.\n\nGracias."
        )
