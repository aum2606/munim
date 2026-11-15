import pytest

from app.ingestion.price_parser import parse_inr
from app.pricing.inr import format_inr


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (0, "₹0.00"),
        (5, "₹0.05"),
        (45000, "₹450.00"),
        (99999, "₹999.99"),
        (100000, "₹1,000.00"),
        (12345678, "₹1,23,456.78"),
        (12000000, "₹1,20,000.00"),
        (1000000000, "₹1,00,00,000.00"),
        (-12345, "-₹123.45"),
    ],
)
def test_format_inr_uses_lakh_grouping(paise: int, expected: str) -> None:
    assert format_inr(paise) == expected


@pytest.mark.parametrize(
    ("text", "paise"),
    [
        ("450", 45000),
        ("1,20,000", 12000000),
        ("₹450/-", 45000),
        ("Rs. 450", 45000),
        ("rs.450", 45000),
        ("INR 1,500", 150000),
        ("1.2L", 12000000),
        ("1.2 lakh", 12000000),
        ("45k", 4500000),
        ("2 cr", 2000000000),
        ("450.50", 45050),
        ("  ₹ 99 only ", 9900),
    ],
)
def test_parse_inr_accepts_indian_price_formats(text: str, paise: int) -> None:
    assert parse_inr(text) == paise


@pytest.mark.parametrize(
    "text", ["", "abc", "₹", "-450", "450.505", "1.2345678k", "12 34", "4,,5k"]
)
def test_parse_inr_rejects_what_it_cannot_read(text: str) -> None:
    with pytest.raises(ValueError):
        parse_inr(text)


def test_round_trip_is_stable() -> None:
    for paise in (1, 99, 100, 123456, 987654321):
        assert parse_inr(format_inr(paise)) == paise
