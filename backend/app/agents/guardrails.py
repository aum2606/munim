"""Checks every outbound customer message must pass. Pure Python, no LLM.

The price check is the rule that matters most: every rupee amount in a reply must equal a price
a tool returned in this same turn. Never weaken it to make a test pass (AGENTS.md section 3).
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

from app.ingestion.price_parser import parse_inr
from app.pricing.inr import format_inr

# Devanagari and Gujarati digits to ASCII so "₹२५०" is checked like "₹250".
_DIGITS = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")

_NUMBER = r"\d+(?:,\d+)*(?:\.\d+)?"
_UNIT = r"(?:k|l|lacs?|lakhs?|cr|crores?)"
_PREFIX = r"(?:₹|rs\.?|inr|रु\.?|रुपये|रुपया|રૂ\.?)"
_SUFFIX = r"(?:rupees?|rupaye|rupiya|rs\.?|inr|/-|/=|रुपये|रुपया|રૂપિયા|રૂ)"
_AMOUNT = re.compile(
    rf"(?<![\w.])(?:{_PREFIX}\s*(?P<n1>{_NUMBER})(?:\s*(?P<u1>{_UNIT})\b)?"
    rf"|(?P<n2>{_NUMBER})(?:\s*(?P<u2>{_UNIT})\b)?\s*{_SUFFIX})",
    re.IGNORECASE,
)

# Phrases from our own system prompts. If one shows up in a reply, the model is leaking them.
_LEAK_MARKERS = (
    "use only information given to you",
    "customer messages (including",
    "<customer_message",
    "reveal or describe these instructions",
    "system prompt",
)
UNREADABLE = -1  # an amount we could not read exactly never matches a real price


@dataclass(frozen=True)
class Violation:
    rule: str  # price | leak | length | empty
    detail: str  # safe to feed back to the model for the retry


def extract_amounts(text: str) -> list[int]:
    """Every rupee amount mentioned in text, in paise. Amounts with more than paisa precision
    come back as UNREADABLE so they are never waved through."""
    amounts: list[int] = []
    for match in _AMOUNT.finditer(text.translate(_DIGITS)):
        number = match["n1"] or match["n2"]
        unit = match["u1"] or match["u2"] or ""
        try:
            amounts.append(parse_inr(f"{number}{unit}"))
        except ValueError:
            amounts.append(UNREADABLE)
    return amounts


def _shown(paise: int) -> str:
    return format_inr(paise) if paise >= 0 else "an unreadable amount"


def check_prices(reply: str, allowed_paise: Collection[int]) -> list[Violation]:
    allowed = set(allowed_paise)
    return [
        Violation("price", f"{_shown(a)} is not a price from the catalogue")
        for a in extract_amounts(reply)
        if a not in allowed
    ]


def check_leakage(reply: str) -> list[Violation]:
    lowered = reply.lower()
    return [
        Violation("leak", "the reply repeats internal instructions")
        for m in _LEAK_MARKERS
        if m in lowered
    ][:1]


def check_reply(reply: str, allowed_paise: Collection[int], max_chars: int) -> list[Violation]:
    if not reply.strip():
        return [Violation("empty", "the reply is empty")]
    violations = check_prices(reply, allowed_paise) + check_leakage(reply)
    if len(reply) > max_chars:
        violations.append(Violation("length", f"the reply is longer than {max_chars} characters"))
    return violations
