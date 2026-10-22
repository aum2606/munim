import re
from decimal import Decimal

from app.core.errors import DomainError
from app.ingestion.price_parser import parse_inr

AMOUNT = r"[+-]?\d[\d,]*(?:\.\d+)?(?:\s*(?:crores?|lakhs?|lac|cr|k|l)\b)?"
MONEY = re.compile(
    r"(?:\u20b9|\bRs\.?|\bINR)\s*"
    + AMOUNT
    + r"(?:/-)?|"
    + AMOUNT
    + r"\s*rupees?\b|(?<![\w])"
    + AMOUNT
    + r"\s*(?:crores?|lakhs?|lac|cr|k|l)\b",
    re.I,
)
MARKER = re.compile(r"\u20b9|\b(?:rs\.?|inr|rupees?)\b", re.I)
DISCOUNT = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(?:off|discount)|discount\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%", re.I
)
LEAK = re.compile(
    r"system prompt|internal notes|ignore (?:all |previous )?instructions|"
    r"api[_ -]?key|secret[_ -]?key",
    re.I,
)


class GuardrailViolation(DomainError):
    pass


def check_prices(text: str, allowed_paise: set[int]) -> None:
    for match in MONEY.finditer(text):
        try:
            paise = parse_inr(match.group())
        except DomainError as error:
            raise GuardrailViolation("Malformed currency amount") from error
        if paise not in allowed_paise:
            raise GuardrailViolation("Price not returned by a tool in this turn")
    if MARKER.search(MONEY.sub("", text)) is not None:
        raise GuardrailViolation("Unrecognized currency amount")


def check_reply(
    text: str,
    allowed_paise: set[int],
    trusted_messages: list[str],
    max_discount_pct: Decimal = Decimal(0),
) -> None:
    check_prices(text, allowed_paise)
    if not text or len(text) > 4000:
        raise GuardrailViolation("Message length exceeds channel limits")
    if LEAK.search(text):
        raise GuardrailViolation("Internal information or instructions detected")
    for match in DISCOUNT.finditer(text):
        if Decimal(match.group(1) or match.group(2)) > max_discount_pct:
            raise GuardrailViolation("Discount exceeds policy")
    if text not in trusted_messages:
        raise GuardrailViolation("Reply includes ungrounded claims")
