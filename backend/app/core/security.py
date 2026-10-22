from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import Unauthorized

DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$iPxW+M5cLxzA0dD32Uadpg$"
    "LMTH/+Kd75eYE5lwDQpv+p63Y8/GTYDLsIBAzCFgCBA"
)


class Claims(BaseModel):
    sub: UUID
    tenant_id: UUID
    kind: Literal["access", "refresh"]
    jti: UUID
    exp: int
    iat: int
    iss: str


def hash_password(password: str) -> str:
    return PasswordHasher().hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return PasswordHasher().verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def issue_token(
    settings: Settings, user_id: UUID, tenant_id: UUID, kind: Literal["access", "refresh"]
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + (
        timedelta(minutes=settings.access_token_minutes)
        if kind == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "kind": kind,
        "jti": str(uuid4()),
        "iat": now,
        "exp": expires,
        "iss": "munim",
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm="HS256"), expires


def decode_token(settings: Settings, token: str, kind: Literal["access", "refresh"]) -> Claims:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=["HS256"],
            issuer="munim",
            options={"require": ["exp", "iat", "sub", "tenant_id", "kind", "jti", "iss"]},
        )
        claims = Claims.model_validate(payload)
        if claims.kind != kind:
            raise Unauthorized()
        return claims
    except (jwt.PyJWTError, ValidationError) as error:
        raise Unauthorized() from error
