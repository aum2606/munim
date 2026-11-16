import re
from decimal import ROUND_HALF_UP, Decimal

GST_RATES = (0, 5, 12, 18, 28)

# 2-digit state code, 10-character PAN, entity number, "Z", check character.
_GSTIN = re.compile(r"^(0[1-9]|[1-2]\d|3[0-8])[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$")


def is_valid_gstin(gstin: str) -> bool:
    """Format check only (it does not verify the check character or that the number exists)."""
    return _GSTIN.match(gstin) is not None


def state_code_of(gstin: str) -> str:
    return gstin[:2]


def gst_split(taxable_paise: int, rate: int, intra_state: bool) -> tuple[int, int, int]:
    """(cgst, sgst, igst) in paise. Intra-state tax is two equal halves, each rounded on its own;
    inter-state tax is a single IGST at the full rate."""
    taxable = Decimal(taxable_paise)
    if intra_state:
        half = int((taxable * rate / Decimal(200)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return half, half, 0
    return 0, 0, int((taxable * rate / Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
