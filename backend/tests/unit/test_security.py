import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

SETTINGS = Settings(app_env="test", secret_key="s" * 40)
USER, TENANT = uuid.uuid4(), uuid.uuid4()


def test_password_round_trip() -> None:
    hashed = hash_password("a long enough password")
    assert hashed != "a long enough password"
    assert verify_password(hashed, "a long enough password")
    assert not verify_password(hashed, "something else")


def test_verify_password_rejects_garbage_hash() -> None:
    assert not verify_password("not-a-hash", "whatever")


def test_access_token_round_trip() -> None:
    claims = decode_access_token(SETTINGS, create_access_token(SETTINGS, USER, TENANT))
    assert (claims.user_id, claims.tenant_id) == (USER, TENANT)


def test_expired_token_is_rejected() -> None:
    expired = Settings(app_env="test", secret_key="s" * 40, access_token_minutes=-1)
    with pytest.raises(UnauthorizedError):
        decode_access_token(SETTINGS, create_access_token(expired, USER, TENANT))


def test_token_signed_with_another_key_is_rejected() -> None:
    other = Settings(app_env="test", secret_key="o" * 40)
    with pytest.raises(UnauthorizedError):
        decode_access_token(SETTINGS, create_access_token(other, USER, TENANT))


def test_unsigned_alg_none_token_is_rejected() -> None:
    forged = jwt.encode({"sub": str(USER), "tid": str(TENANT), "typ": "access"}, None, "none")
    with pytest.raises(UnauthorizedError):
        decode_access_token(SETTINGS, forged)


def test_token_of_wrong_type_is_rejected() -> None:
    payload = {
        "sub": str(USER),
        "tid": str(TENANT),
        "typ": "refresh",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    with pytest.raises(UnauthorizedError):
        decode_access_token(SETTINGS, jwt.encode(payload, SETTINGS.secret_key, "HS256"))


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(UnauthorizedError):
        decode_access_token(SETTINGS, "not.a.jwt")


def test_refresh_token_is_random_and_stored_hashed() -> None:
    raw1, hash1 = new_refresh_token()
    raw2, _ = new_refresh_token()
    assert raw1 != raw2
    assert hash1 == hash_refresh_token(raw1) and raw1 not in hash1
