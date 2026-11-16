from datetime import date


def fiscal_year(on: date) -> str:
    """Indian financial year (April to March) as '2026-27'. Pass the date in IST."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def format_quote_number(fiscal_year_label: str, sequence: int) -> str:
    return f"Q/{fiscal_year_label}/{sequence:04d}"
