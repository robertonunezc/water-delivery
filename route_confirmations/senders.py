from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import quote

from notification.channels.email import SendEmail


@dataclass(frozen=True)
class ConfirmationMessage:
    recipient: str
    subject: str
    body: str
    client_name: str
    visit_date: str
    confirm_url: str
    do_not_visit_url: str


@dataclass(frozen=True)
class SendReceipt:
    recipient: str
    channel: str
    success: bool
    error: str = ''
    delivery_url: str = ''

    def as_dict(self) -> dict[str, str | bool]:
        data: dict[str, str | bool] = {
            'recipient': self.recipient,
            'channel': self.channel,
            'success': self.success,
            'error': self.error,
        }
        if self.delivery_url:
            data['delivery_url'] = self.delivery_url
        return data


class BaseConfirmationSender(ABC):
    @abstractmethod
    def send(self, message: ConfirmationMessage) -> SendReceipt:
        pass


class EmailConfirmationSender(BaseConfirmationSender):
    channel = 'email'

    def send(self, message: ConfirmationMessage) -> SendReceipt:
        try:
            SendEmail(
                to=message.recipient,
                from_='PuriGest <no-reply@purigest.com>',
                subject=message.subject,
                body=message.body,
            ).send_email()
        except Exception as exc:
            return SendReceipt(
                recipient=message.recipient,
                channel=self.channel,
                success=False,
                error=str(exc),
            )
        return SendReceipt(
            recipient=message.recipient,
            channel=self.channel,
            success=True,
        )


class WhatsAppConfirmationSender(BaseConfirmationSender):
    channel = 'whatsapp'

    def send(self, message: ConfirmationMessage) -> SendReceipt:
        phone = normalize_whatsapp_phone(message.recipient)
        if not phone:
            return SendReceipt(
                recipient=message.recipient,
                channel=self.channel,
                success=False,
                error='Número de WhatsApp inválido',
            )

        return SendReceipt(
            recipient=phone,
            channel=self.channel,
            success=True,
            delivery_url=build_whatsapp_url(phone, message.body),
        )


def normalize_whatsapp_phone(phone: str) -> str:
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('00'):
        digits = digits[2:]
    if len(digits) < 10:
        return ''
    if len(digits) == 10:
        return f'52{digits}'
    return digits


def build_whatsapp_url(phone: str, message: str) -> str:
    encoded_message = quote(message.strip(), safe='')
    return f'https://wa.me/{phone}?text={encoded_message}'


class ConfirmationSenderFactory:
    @staticmethod
    def get_sender(channel: str) -> BaseConfirmationSender:
        if channel == 'email':
            return EmailConfirmationSender()
        if channel == 'whatsapp':
            return WhatsAppConfirmationSender()
        raise ValueError(f'Canal de confirmación no soportado: {channel}')
