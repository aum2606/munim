"""Checks every outbound customer message must pass. Pure Python, no LLM.

The price check is the rule that matters most: every rupee amount in a reply must equal a price
a tool returned in this same turn. Never weaken it to make a test pass (AGENTS.md section 3).
"""

from collections.abc import Collection
from dataclasses import dataclass

from app.agents.amounts import UNREADABLE, extract_amounts, normalise
from app.pricing.inr import format_inr

# Phrases from our own system prompts. If one shows up in a reply, the model is leaking them.
_LEAK_MARKERS = (
    "use only information given to you",
    "customer messages (including",
    "<customer_message",
    "reveal or describe these instructions",
    "system prompt",
)


@dataclass(frozen=True)
class Violation:
    rule: str  # price | leak | length | empty
    detail: str  # safe to feed back to the model for the retry


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
    lowered = " ".join(normalise(reply).lower().split())  # spacing tricks do not hide a phrase
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


__all__ = [
    "UNREADABLE",
    "Violation",
    "check_leakage",
    "check_prices",
    "check_reply",
    "extract_amounts",
]
