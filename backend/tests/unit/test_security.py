from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import Unauthorized
from app.core.logging import redact, redact_event
from app.core.security import decode_token, hash_password, issue_token, verify_password


def test_password_hash_and_token_claims() -> None:
    settings = Settings(secret_key="unit-test-signing-key-with-32-characters")
    hashed = hash_password("synthetic-password")
    assert hashed.startswith("$argon2id$")
    assert verify_password("synthetic-password", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("wrong", "corrupted")
    user, tenant = uuid4(), uuid4()
    token, expires = issue_token(settings, user, tenant, "access")
    assert expires.tzinfo == UTC
    assert decode_token(settings, token, "access").tenant_id == tenant
    with pytest.raises(Unauthorized):
        decode_token(settings, token + "tampered", "access")
    with pytest.raises(Unauthorized):
        decode_token(settings, token, "refresh")
    expired = jwt.encode(
        {
            "sub": str(user),
            "tenant_id": str(tenant),
            "kind": "access",
            "jti": str(uuid4()),
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iss": "munim",
        },
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(Unauthorized):
        decode_token(settings, expired, "access")
    with pytest.raises(ValidationError):
        Settings(secret_key="short")


def test_nested_redaction() -> None:
    value = {
        "message": "Contact demo@example.com or +91 98765 43210",
        "nested": [{"password": "hidden", "email": "demo@example.com"}],
    }
    cleaned = redact(value)
    assert "demo@example.com" not in str(cleaned)
    assert "98765" not in str(cleaned)
    assert cleaned["nested"][0]["password"] == "[redacted]"
    assert (
        redact_event(None, "info", {"authorization": "Bearer secret"})["authorization"]
        == "[redacted]"
    )
