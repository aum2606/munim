import io
from zipfile import ZipFile

import pytest

from app.core.errors import DomainError
from app.ingestion.catalog_files import read_table, template_xlsx
from app.ingestion.price_parser import parse_inr
from app.pricing.inr import format_inr


@pytest.mark.parametrize(
    "text,paise",
    [
        ("1,20,000", 12000000),
        ("1.2L", 12000000),
        ("45k", 4500000),
        ("\u20b9450/-", 45000),
        ("Rs. 450", 45000),
        ("INR 0.01", 1),
        ("1 crore", 1000000000),
        ("1,234.56", 123456),
        ("0", 0),
        ("1,234,567", 123456700),
    ],
)
def test_price_parser(text: str, paise: int) -> None:
    assert parse_inr(text) == paise


@pytest.mark.parametrize(
    "text", ["-1", "NaN", "inf", "1e3", "12,34", "free", "1.001", "", "92233720368547758.08"]
)
def test_invalid_money(text: str) -> None:
    with pytest.raises(DomainError):
        parse_inr(text)


@pytest.mark.parametrize(
    "paise,text",
    [
        (0, "\u20b90.00"),
        (1, "\u20b90.01"),
        (45000, "\u20b9450.00"),
        (12345678, "\u20b91,23,456.78"),
        (12345678900, "\u20b912,34,56,789.00"),
        (-101, "-\u20b91.01"),
    ],
)
def test_format_inr(paise: int, text: str) -> None:
    assert format_inr(paise) == text


def test_template_and_raw_numeric_xlsx_avoid_float_coercion() -> None:
    template = template_xlsx()
    headers, rows = read_table("template.xlsx", template)
    assert rows[0]["price"] == "450"
    source = io.BytesIO(template)
    output = io.BytesIO()
    with ZipFile(source) as original, ZipFile(output, "w") as amended:
        for name in original.namelist():
            content = original.read(name)
            if name == "xl/worksheets/sheet1.xml":
                content = content.replace(
                    b'<c r="G2" t="inlineStr"><is><t>450</t></is></c>',
                    b'<c r="G2" t="n"><v>123456789.01</v></c>',
                )
            amended.writestr(name, content)
    assert read_table("numeric.xlsx", output.getvalue())[1][0]["price"] == "123456789.01"
    assert headers[0] == "sku"


def test_invalid_catalogue_files() -> None:
    for filename, content in [
        ("bad.csv", b"sku,sku\na,b"),
        ("bad.csv", b"a,b\na,b,c"),
        ("empty.csv", b""),
        ("bad.exe", b"a,b"),
        ("bad.xlsx", b"not zip"),
    ]:
        with pytest.raises(DomainError):
            read_table(filename, content)


def test_structured_catalog_price():
    from uuid import uuid4

    from app.db.models import CatalogItem
    from app.pricing.catalog import catalog_price

    catalog = CatalogItem(
        id=uuid4(), tenant_id=uuid4(), sku="CARD", name="Cards", base_price_paise=45000
    )
    price = catalog_price(catalog)
    assert price.paise == 45000 and price.formatted == "\u20b9450.00"
