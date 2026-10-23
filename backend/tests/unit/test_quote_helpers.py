from datetime import UTC, datetime

import pytest

from app.pricing.inr import amount_in_words
from app.pricing.quote_number import financial_year, next_quote_number


@pytest.mark.parametrize(
    "paise,expected",
    [
        (0, "Rupees Zero Only"),
        (2500, "Rupees Twenty Five Only"),
        (2000, "Rupees Twenty Only"),
        (10000, "Rupees One Hundred Only"),
        (10100, "Rupees One Hundred One Only"),
        (100000, "Rupees One Thousand Only"),
        (100100, "Rupees One Thousand One Only"),
        (10000000, "Rupees One Lakh Only"),
        (10000100, "Rupees One Lakh One Only"),
        (1000000000, "Rupees One Crore Only"),
        (1000000101, "Rupees One Crore One and One Paise Only"),
    ],
)
def test_indian_amount_words(paise, expected):
    assert amount_in_words(paise) == expected


def test_financial_year_uses_indian_midnight_boundary():
    assert financial_year(datetime(2026, 3, 31, 18, 29, tzinfo=UTC)) == "2025-26"
    assert financial_year(datetime(2026, 3, 31, 18, 30, tzinfo=UTC)) == "2026-27"
    with pytest.raises(ValueError):
        financial_year(datetime(2026, 4, 1))


async def test_number_format_and_current_year_default():
    class Counter:
        async def next_for_year(self, year):
            return 1

    assert await next_quote_number(Counter(), datetime(2026, 4, 1, tzinfo=UTC)) == "Q/2026-27/0001"
    assert (await next_quote_number(Counter())).endswith("/0001")
