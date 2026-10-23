from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class QuoteCounter(Protocol):
    async def next_for_year(self, financial_year: str) -> int: ...


def financial_year(when: datetime) -> str:
    if when.tzinfo is None:
        raise ValueError("Quote dates require a timezone")
    local = when.astimezone(ZoneInfo("Asia/Kolkata"))
    start = local.year if local.month >= 4 else local.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


async def next_quote_number(tenant: QuoteCounter, when: datetime | None = None) -> str:
    year = financial_year(when or datetime.now(UTC))
    sequence = await tenant.next_for_year(year)
    return f"Q/{year}/{sequence:04d}"
