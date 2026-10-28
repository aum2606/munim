import logging
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
    "app_secret",
    "client_secret",
    "credentials_encrypted",
    "consent_note",
    "token",
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


class StandardLogRedactor(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            arguments = list(record.args)
            if record.name == "uvicorn.access" and len(arguments) >= 5:
                arguments[2] = str(arguments[2]).split("?", 1)[0]
            record.args = tuple(redact(value) for value in arguments)
        elif isinstance(record.args, dict):
            record.args = redact(record.args)
        record.msg = redact(str(record.msg))
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def configure_logging() -> None:
    # Provider/media URLs can contain temporary credentials; do not emit HTTP request URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    for name in ("uvicorn.access", "uvicorn.error", "arq.worker", "arq.jobs"):
        logger = logging.getLogger(name)
        if not any(isinstance(value, StandardLogRedactor) for value in logger.filters):
            logger.addFilter(StandardLogRedactor())
    for handler in logging.getLogger().handlers:
        if not any(isinstance(value, StandardLogRedactor) for value in handler.filters):
            handler.addFilter(StandardLogRedactor())
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            redact_event,
            structlog.processors.JSONRenderer(),
        ]
    )
