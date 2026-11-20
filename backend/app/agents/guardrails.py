"""Checks every outbound customer message must pass. Pure Python, no LLM.

The price check is the rule that matters most: every rupee amount in a reply must equal a price
a tool returned in this same turn. Never weaken it to make a test pass (AGENTS.md section 3).
Contact and payment details follow the same rule: only the shop's own may be repeated.

Each check is a function in CHECKS, so a new guardrail is added to the list, not edited into one.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass

from app.agents.amounts import UNREADABLE, extract_amounts, normalise
from app.agents.contacts import Contact, unknown_contacts
from app.agents.leakage import leaks_canary, overlaps_prompt
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
    rule: str  # price | contact | leak | length | empty
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


def check_contacts(reply: str, allowed: Collection[Contact] = ()) -> list[Violation]:
    """A phone number, link, email, UPI ID or bank detail that is not the shop's own."""
    kinds = sorted({kind for kind, _ in unknown_contacts(reply, allowed)})
    return [
        Violation("contact", f"a {kind} that is not in the shop's own details must not be given")
        for kind in kinds
    ]


def check_leakage(reply: str) -> list[Violation]:
    lowered = " ".join(normalise(reply).lower().split())  # spacing tricks do not hide a phrase
    leaked = (
        any(m in lowered for m in _LEAK_MARKERS) or leaks_canary(reply) or overlaps_prompt(reply)
    )
    return [Violation("leak", "the reply repeats internal instructions")] if leaked else []


@dataclass(frozen=True)
class ReplyContext:
    allowed_paise: Collection[int]
    allowed_contacts: Collection[Contact]
    max_chars: int


Check = Callable[[str, ReplyContext], list[Violation]]

CHECKS: tuple[Check, ...] = (
    lambda reply, ctx: check_prices(reply, ctx.allowed_paise),
    lambda reply, ctx: check_contacts(reply, ctx.allowed_contacts),
    lambda reply, ctx: check_leakage(reply),
    lambda reply, ctx: (
        [Violation("length", f"the reply is longer than {ctx.max_chars} characters")]
        if len(reply) > ctx.max_chars
        else []
    ),
)


def check_reply(
    reply: str,
    allowed_paise: Collection[int],
    max_chars: int,
    *,
    allowed_contacts: Collection[Contact] = (),
) -> list[Violation]:
    if not reply.strip():
        return [Violation("empty", "the reply is empty")]
    ctx = ReplyContext(allowed_paise, allowed_contacts, max_chars)
    return [violation for check in CHECKS for violation in check(reply, ctx)]


__all__ = [
    "UNREADABLE",
    "Violation",
    "check_contacts",
    "check_leakage",
    "check_prices",
    "check_reply",
    "extract_amounts",
]
