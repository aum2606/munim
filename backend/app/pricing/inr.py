def format_inr(paise: int) -> str:
    """Integer paise to Indian-grouped rupees: 12345678 -> '₹1,23,456.78'. No floats."""
    rupees, remainder = divmod(abs(paise), 100)
    digits = str(rupees)
    head, tail = digits[:-3], digits[-3:]  # last three digits, then groups of two
    groups: list[str] = []
    while len(head) > 2:
        groups.append(head[-2:])
        head = head[:-2]
    if head:
        groups.append(head)
    grouped = ",".join([*reversed(groups), tail])
    sign = "-" if paise < 0 else ""
    return f"{sign}₹{grouped}.{remainder:02d}"


_ONES = [
    "Zero",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]
_TENS = [
    "Zero",
    "Ten",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
]


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def _indian_words(n: int) -> str:
    """A whole number (n >= 1) in words, using crore, lakh and thousand."""
    crore, rest = divmod(n, 10_000_000)
    parts = []
    if crore:
        parts.append(f"{_indian_words(crore)} Crore")
    for size, name in ((100_000, "Lakh"), (1_000, "Thousand")):
        count, rest = divmod(rest, size)
        if count:
            parts.append(f"{_below_hundred(count)} {name}")
    if rest:
        parts.append(_below_thousand(rest))
    return " ".join(parts)


def amount_in_words(paise: int) -> str:
    """e.g. 'Rupees One Thousand Six Hundred Fifty-Two and Five Paise Only'."""
    if paise < 0:
        raise ValueError("amount must not be negative")
    rupees, remainder = divmod(paise, 100)
    text = f"Rupees {_indian_words(rupees) if rupees else 'Zero'}"
    if remainder:
        text += f" and {_below_hundred(remainder)} Paise"
    return text + " Only"
