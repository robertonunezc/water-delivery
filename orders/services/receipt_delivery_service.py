from __future__ import annotations

from typing import Protocol

from django.conf import settings
from django.utils import timezone

from notification.channels.email import EmailAttachment, SendEmail
from orders.models import OrderReceipt, ReceiptDeliveryMethod
from orders.services.receipt_storage_service import get_receipt_storage


class ReceiptDeliveryError(RuntimeError):
    """Raised when a receipt cannot be delivered."""


class ReceiptSender(Protocol):
    def send(self, receipt: OrderReceipt) -> None:
        ...


class EmailReceiptSender:
    def send(self, receipt: OrderReceipt) -> None:
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


class ReceiptSenderFactory:
    def __init__(self) -> None:
        self._senders: dict[str, ReceiptSender] = {
            ReceiptDeliveryMethod.EMAIL: EmailReceiptSender(),
        }

    def get_sender(self, method: str) -> ReceiptSender:
        sender = self._senders.get(method)
        if sender is None:
            raise ReceiptDeliveryError(f"Metodo de envio no soportado: {method}")
        return sender


class ReceiptDeliveryService:
    def __init__(self, factory: ReceiptSenderFactory | None = None) -> None:
        self.factory = factory or ReceiptSenderFactory()

    def send(self, receipt: OrderReceipt) -> OrderReceipt:
        try:
            self.factory.get_sender(receipt.method).send(receipt)
        except Exception as exc:
            raise ReceiptDeliveryError(str(exc)) from exc

        receipt.sent_at = timezone.now()
        receipt.save(update_fields=["sent_at", "updated_at"])
        return receipt
