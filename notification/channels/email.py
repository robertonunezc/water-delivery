import os
from django.http import response
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


class SendNotification(ABC):
    to: str
    from_: str
    subject: str
    body: str

    @abstractmethod
    def send_email(self) -> None:
        pass


class SendEmail(SendNotification):
    def __init__(
        self,
        to: str,
        from_: str,
        subject: str,
        body: str,
        attachments: Iterable[EmailAttachment] | None = None,
    ) -> None:
        self.to = to
        self.from_ = os.getenv('SEND_EMAIL_FROM', from_)
        self.subject = subject
        self.body = body
        self.attachments = list(attachments or [])

    def send_email(self) -> None:
        email_api_key = os.getenv('SEND_EMAIL_KEY', 'SEND_EMAIL_KEY')
        from_domain = os.getenv('SEND_EMAIL_DOMAIN', 'SEND_EMAIL_DOMAIN')
        print(
            f"Enviando email a {self.to} usando dominio {from_domain} "
            f"from: {self.from_}"
        )
        files = [
            (
                "attachment",
                (attachment.filename, attachment.content, attachment.content_type),
            )
            for attachment in self.attachments
        ]
        
        response = requests.post(
            f"https://api.mailgun.net/v3/{from_domain}/messages",
            auth=("api", email_api_key),
            data={
                "from": self.from_,
                "to": self.to,
                "subject": self.subject,
                "text": self.body,
            },
            files=files or None,
        )
        print("STATUS:", response.status_code)
        print("BODY:", response.text)       
        if response.status_code != 200:
            print(f"Error al enviar el email: {response.text}")
            raise Exception(f"Error al enviar el email: {response.text}")
