def format_inr(paise: int) -> str:
    negative = paise < 0
    rupees, fraction = divmod(abs(paise), 100)
    digits = str(rupees)
    tail, head = digits[-3:], digits[:-3]
    groups: list[str] = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    groups.append(tail)
    return ("-" if negative else "") + "\u20b9" + ",".join(groups) + f".{fraction:02d}"


def _number_words(number: int) -> str:
    ones = (
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
    )
    tens = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")
    if number < 20:
        return ones[number]
    if number < 100:
        return tens[number // 10] + (" " + ones[number % 10] if number % 10 else "")
    if number < 1000:
        divisor, label = 100, "Hundred"
    elif number < 100_000:
        divisor, label = 1000, "Thousand"
    elif number < 10_000_000:
        divisor, label = 100_000, "Lakh"
    else:
        divisor, label = 10_000_000, "Crore"
    quotient, remainder = divmod(number, divisor)
    return (
        _number_words(quotient)
        + " "
        + label
        + (" " + _number_words(remainder) if remainder else "")
    )


def amount_in_words(paise: int) -> str:
    from pydantic import TypeAdapter

    from app.schemas.pricing import Paise

    checked = TypeAdapter(Paise).validate_python(paise)
    rupees, fraction = divmod(checked, 100)
    return (
        "Rupees "
        + _number_words(rupees)
        + (" and " + _number_words(fraction) + " Paise" if fraction else "")
        + " Only"
    )
