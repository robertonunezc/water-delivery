from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

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

    def as_dict(self) -> dict[str, str | bool]:
        return {
            'recipient': self.recipient,
            'channel': self.channel,
            'success': self.success,
            'error': self.error,
        }


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


class ConfirmationSenderFactory:
    @staticmethod
    def get_sender(channel: str) -> BaseConfirmationSender:
        if channel == 'email':
            return EmailConfirmationSender()
        raise ValueError(f'Canal de confirmación no soportado: {channel}')
