from decimal import ROUND_HALF_UP, Decimal


def paise_round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def gst_split(taxable_paise: int, rate: int, interstate: bool) -> tuple[int, int, int]:
    # CBIC supply distinction: https://cbic-gst.gov.in/hindi/faq.html
    if interstate:
        return 0, 0, paise_round(Decimal(taxable_paise) * Decimal(rate) / Decimal(100))
    half = paise_round(Decimal(taxable_paise) * Decimal(rate) / Decimal(200))
    return half, half, 0
