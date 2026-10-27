from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core.errors import DomainError


def cipher(key: SecretStr) -> Fernet:
    try:
        return Fernet(key.get_secret_value().encode())
    except (ValueError, TypeError) as error:
        raise DomainError(
            "Configure a valid CREDENTIALS_ENCRYPTION_KEY before connecting channels", 503
        ) from error


def encrypt_credential(key: SecretStr, token: SecretStr) -> str:
    return cipher(key).encrypt(token.get_secret_value().encode()).decode()


def decrypt_credential(key: SecretStr, encrypted: str) -> str:
    try:
        return cipher(key).decrypt(encrypted.encode()).decode()
    except (InvalidToken, UnicodeError) as error:
        raise DomainError(
            "Channel credentials could not be decrypted; reconnect the account", 503
        ) from error
