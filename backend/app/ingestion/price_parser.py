import re
from decimal import Decimal, InvalidOperation

from app.core.errors import DomainError

NUMBER = re.compile(r"^(\d[\d,]*(?:\.\d+)?)(k|l|lac|lakh|lakhs|cr|crore|crores)?$", re.I)
GROUPED = re.compile(r"^(?:\d{1,3}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+)$")
MULTIPLIERS = {
    "": 1,
    "k": 1000,
    "l": 100000,
    "lac": 100000,
    "lakh": 100000,
    "lakhs": 100000,
    "cr": 10000000,
    "crore": 10000000,
    "crores": 10000000,
}


def parse_inr(text: str) -> int:
    cleaned = re.sub(r"^(?:\u20b9|rs\.?|inr)\s*", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"(?:/-|rupees?|inr)$", "", cleaned, flags=re.I).strip().replace(" ", "")
    match = NUMBER.fullmatch(cleaned)
    if match is None:
        raise DomainError("Invalid INR amount")
    number, suffix = match.groups()
    whole = number.split(".")[0]
    if "," in whole and GROUPED.fullmatch(whole) is None:
        raise DomainError("Invalid INR grouping")
    try:
        paise = Decimal(number.replace(",", "")) * MULTIPLIERS[(suffix or "").lower()] * 100
        if paise != paise.to_integral_value() or paise > 9223372036854775807:
            raise DomainError("INR amount must fit integer paise")
        return int(paise)
    except InvalidOperation as error:
        raise DomainError("Invalid INR amount") from error
