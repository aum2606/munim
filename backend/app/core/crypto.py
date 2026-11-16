"""Encryption of channel credentials at rest (AGENTS.md: stored encrypted)."""

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings


def _fernet(settings: Settings) -> Fernet:
    if settings.credentials_encryption_key:
        return Fernet(settings.credentials_encryption_key.encode())
    # Dev/test only: prod refuses to start without a real key (see Settings).
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()))


def encrypt_credentials(settings: Settings, credentials: dict[str, Any]) -> str:
    return _fernet(settings).encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(settings: Settings, token: str) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(_fernet(settings).decrypt(token.encode()))
    except InvalidToken as exc:  # wrong key: never include the token in the message
        raise ValueError("Stored credentials cannot be decrypted with the current key") from exc
    return data
