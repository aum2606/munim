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
