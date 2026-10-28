import re
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)")
SENSITIVE = {
    "password",
    "password_hash",
    "authorization",
    "access_token",
    "refresh_token",
    "api_key",
    "secret",
}


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return PHONE.sub("[phone]", EMAIL.sub("[email]", value))
    if isinstance(value, Mapping):
        return {k: "[redacted]" if k.lower() in SENSITIVE else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def redact_event(logger: object, method: str, event: MutableMapping[str, Any]) -> dict[str, Any]:
    return {
        key: "[redacted]" if key.lower() in SENSITIVE else redact(value)
        for key, value in event.items()
    }


def configure_logging() -> None:
    import logging

    # Provider/media URLs can contain temporary credentials; do not emit HTTP request URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            redact_event,
            structlog.processors.JSONRenderer(),
        ]
    )
