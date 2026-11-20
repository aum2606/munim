"""The SMTP mailer talks to the configured server and nothing else; a fake stands in for tests."""

import smtplib
from email.message import EmailMessage
from typing import Any

import pytest

from app.core.config import Settings
from app.services.mailer import FakeMailer, SmtpMailer


class FakeSmtp:
    calls: list[tuple[str, Any]] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.calls.append(("connect", (host, port)))

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append(("quit", None))

    def starttls(self) -> None:
        self.calls.append(("starttls", None))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user))

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append(("send", (message["To"], message["From"], message["Subject"])))


def settings(**over: object) -> Settings:
    base = {"smtp_host": "smtp.test", "smtp_from": "noreply@munim.test", "secret_key": "k" * 40}
    return Settings(_env_file=None, **{**base, **over})  # type: ignore[arg-type]


async def test_it_connects_secures_logs_in_and_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.calls = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    mailer = SmtpMailer(settings(smtp_user="u", smtp_password="p"))
    await mailer.send("owner@example.com", "Hello", "Body")
    assert FakeSmtp.calls == [
        ("connect", ("smtp.test", 587)),
        ("starttls", None),
        ("login", "u"),
        ("send", ("owner@example.com", "noreply@munim.test", "Hello")),
        ("quit", None),
    ]


async def test_it_skips_login_without_credentials_and_tls_when_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSmtp.calls = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    await SmtpMailer(settings(smtp_starttls=False)).send("a@example.com", "S", "B")
    assert [name for name, _ in FakeSmtp.calls] == ["connect", "send", "quit"]


async def test_the_fake_records_instead_of_sending() -> None:
    fake = FakeMailer()
    await fake.send("a@example.com", "S", "B")
    assert fake.sent == [("a@example.com", "S", "B")]


def test_mail_is_ready_only_with_a_host_and_a_sender() -> None:
    assert settings().mail_ready
    assert not settings(smtp_host="").mail_ready
    assert not settings(smtp_from="").mail_ready
