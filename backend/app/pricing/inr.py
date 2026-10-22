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
