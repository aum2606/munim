import re
from decimal import Decimal

# "1.2L", "45k", "2 cr": multipliers on the rupee amount
_MULTIPLIERS = {
    "k": Decimal(1_000),
    "l": Decimal(100_000),
    "lac": Decimal(100_000),
    "lacs": Decimal(100_000),
    "lakh": Decimal(100_000),
    "lakhs": Decimal(100_000),
    "cr": Decimal(10_000_000),
    "crore": Decimal(10_000_000),
    "crores": Decimal(10_000_000),
}

_PRICE = re.compile(
    r"""^\s*
    (?:₹|rs\.?|inr|rupees?)?\s*          # optional currency prefix
    (?P<number>\d+(?:,\d+)*(?:\.\d+)?)   # 1,20,000 / 450 / 450.50
    \s*(?P<unit>k|l|lacs?|lakhs?|cr|crores?)?   # optional multiplier
    \s*(?:/-|/=|only)?\s*$               # optional "/-" suffix
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_inr(text: str) -> int:
    """Parse an Indian price string into integer paise.

    Handles '1,20,000', '1.2L', '45k', '₹450/-', 'Rs. 450', '450.50'. Raises ValueError for
    anything else, or for more precision than a paisa, so a bad price is never guessed.
    """
    match = _PRICE.match(text)
    if match is None:
        raise ValueError("not a recognisable rupee amount")
    rupees = Decimal(match["number"].replace(",", ""))
    if match["unit"]:
        rupees *= _MULTIPLIERS[match["unit"].lower()]
    paise = rupees * 100
    if paise != paise.to_integral_value():
        raise ValueError("more precision than a paisa")
    return int(paise)
