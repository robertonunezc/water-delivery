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
        return requests.post(
            "https://api.mailgun.net/v3/sandbox40fe3482053c4675b353e6270f32bbe5.mailgun.org/messages",
            auth=("api", email_api_key),
            data={"from": "Mailgun Sandbox <postmaster@sandbox40fe3482053c4675b353e6270f32bbe5.mailgun.org>",
                "to": self.to,
                "subject": self.subject,
                "text": self.body})