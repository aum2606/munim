"""Finding ways to reach someone or pay someone in free text. Pure Python, no LLM.

A reply may only point a customer at the shop's own contact details. Anything else (a phone number,
a UPI ID, a link, an email, a bank account) could send the customer's money or attention to a
stranger, which is the classic fraud after a prompt injection, so it is refused unless the same
contact appears in the shop's own data this turn (its profile, its FAQs, its catalogue).

Every contact becomes a (kind, key) pair with the key normalised, so the allowed list and the reply
compare equal however each is written: `+91 98765-43210`, `९८७६५४३२१०` and `9876543210` are one
phone.
"""

import re
from collections.abc import Iterable

from app.agents.amounts import normalise, strip_amounts

Contact = tuple[str, str]  # (kind, normalised key)

_TLDS = (
    "com|in|co|org|net|io|me|app|link|xyz|ly|gl|page|dev|shop|store|online|site|info|biz|club|top|"
    "cc|tk|ml|ga|cf|gq|ws|to|vip|live|fun|click|work|world|today|tech|space|pro|email|cloud"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_UPI = re.compile(r"(?<![\w.])[\w.-]{2,}@[a-z]{2,}(?!\w|\.\w)", re.IGNORECASE)
_URL = re.compile(
    rf"\b(?:https?://|www\.)[^\s<>\"')]+"
    rf"|\b(?:[a-z0-9-]+\.)+[a-z]{{2,}}/[^\s<>\"')]+"  # any host followed by a path
    rf"|\b(?:[a-z0-9-]+\.)+(?:{_TLDS})\b",
    re.IGNORECASE,
)
_IFSC = re.compile(r"\b[a-z]{4}0[a-z0-9]{6}\b", re.IGNORECASE)
_NUMBER_RUN = re.compile(r"(?<![\d])\+?\d[\d\s().-]{7,}\d(?!\d)")
_DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_SPELLED = re.compile(rf"\b(?:(?:{'|'.join(_DIGIT_WORDS)})(?:[\s,.-]+|\b)){{7,}}", re.IGNORECASE)
_DOT = re.compile(
    r"(?<=\w)\s*[\[(]\s*dot\s*[\])]\s*(?=\w)|(?<=\w)\s+dot\s+(?=(?:" + _TLDS + r")\b)",
    re.IGNORECASE,
)
_AT = re.compile(r"(?<=\w)\s*[\[(]\s*at\s*[\])]\s*(?=\w)", re.IGNORECASE)
_MIN_DIGITS = 9  # a date is 8 digits; a mobile number is 10; an account number 9 to 18


def _deobfuscate(text: str) -> str:
    """ "name (at) shop (dot) com" and "shop dot com" read as the address they stand for."""
    return _AT.sub("@", _DOT.sub(".", text))


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _spelled_digits(match: str) -> str:
    words = re.findall("|".join(_DIGIT_WORDS), match.lower())
    return "".join(str(_DIGIT_WORDS.index(w)) for w in words)


def _host(url: str) -> str:
    host = re.sub(r"^https?://", "", url.lower()).split("/")[0].split("?")[0]
    return host.removeprefix("www.")


def extract_contacts(text: str) -> set[Contact]:
    """Every contact or payment detail in the text, normalised. Rupee amounts are blanked first."""
    text = _deobfuscate(strip_amounts(text))
    found: set[Contact] = set()
    for match in _EMAIL.finditer(text):
        found.add(("email", match[0].lower()))
    text = _EMAIL.sub(" ", text)
    for match in _UPI.finditer(text):
        found.add(("upi", match[0].lower()))
    text = _UPI.sub(" ", text)
    for match in _URL.finditer(text):
        found.add(("url", _host(match[0])))
    text = _URL.sub(" ", text)
    for match in _IFSC.finditer(text):
        found.add(("ifsc", match[0].upper()))
    for match in _NUMBER_RUN.finditer(text):
        digits = _digits(match[0])
        if len(digits) >= _MIN_DIGITS:
            found.add(("number", digits[-10:] if len(digits) <= 12 else digits))
    for match in _SPELLED.finditer(text):
        digits = _spelled_digits(match[0])
        if len(digits) >= 7:
            found.add(("number", digits[-10:]))
    return found


def allowed_contacts(*texts: str | None) -> frozenset[Contact]:
    """The contacts a reply may repeat: those present in the shop's own data."""
    found: set[Contact] = set()
    for text in texts:
        if text:
            found |= extract_contacts(text)
    return frozenset(found)


def unknown_contacts(reply: str, allowed: Iterable[Contact]) -> list[Contact]:
    return sorted(extract_contacts(reply) - set(allowed))


__all__ = ["Contact", "allowed_contacts", "extract_contacts", "normalise", "unknown_contacts"]
