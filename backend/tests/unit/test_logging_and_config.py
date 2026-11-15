import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import redact


def test_redact_masks_emails_and_phones_in_nested_data() -> None:
    cleaned = redact({"a": "mail ravi@shop.in or +91 98765 43210", "b": ["call 9876543210"]})
    assert "ravi@shop.in" not in str(cleaned)
    assert "98765" not in str(cleaned)
    assert "9876543210" not in str(cleaned)
    assert "[email]" in cleaned["a"] and "[phone]" in cleaned["b"][0]


def test_redact_leaves_other_values_alone() -> None:
    assert redact({"n": 5, "s": "hello"}) == {"n": 5, "s": "hello"}


def test_prod_rejects_weak_or_placeholder_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="prod", secret_key="short")
    with pytest.raises(ValidationError):
        Settings(app_env="prod", secret_key="please-change-me-" + "x" * 30)
    assert Settings(app_env="prod", secret_key="k" * 40).secure_cookies


def test_cors_origins_parsing() -> None:
    assert Settings(cors_origins=" http://a.com, http://b.com ,").cors_origin_list == [
        "http://a.com",
        "http://b.com",
    ]
    assert Settings(cors_origins="").cors_origin_list == []
