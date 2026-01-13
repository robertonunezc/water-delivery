import os
import requests
from abc import ABC, abstractmethod

class SendNotification(ABC):
    to: str
    from_: str
    subject: str
    body: str
    @abstractmethod
    def send_email(self):
        pass

class SendEmail(SendNotification):
    def __init__(self, to: str, from_: str, subject: str, body: str):
        self.to = to
        self.from_ = from_
        self.subject = subject
        self.body = body
    def send_email(self):
        email_api_key = os.getenv('SEND_EMAIL_KEY', 'SEND_EMAIL_KEY')
        from_domain = os.getenv('SEND_EMAIL_DOMAIN', 'SEND_EMAIL_DOMAIN')
        return requests.post(
            f"https://api.mailgun.net/v3/{from_domain}/messages",
            auth=("api", email_api_key),
            data={"from": self.from_,
                "to": self.to,
                "subject": self.subject,
                "text": self.body})