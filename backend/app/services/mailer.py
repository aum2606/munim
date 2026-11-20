"""Sending email. SMTP from the standard library, so no provider SDK and no paid service."""

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self._s.smtp_from, to, subject
        message.set_content(body)
        await asyncio.to_thread(self._send_blocking, message)

    def _send_blocking(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=20) as smtp:
            if self._s.smtp_starttls:
                smtp.starttls()
            if self._s.smtp_user:
                smtp.login(self._s.smtp_user, self._s.smtp_password)
            smtp.send_message(message)


class FakeMailer:
    """Collects what would have been sent. Tests never touch a network."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))
