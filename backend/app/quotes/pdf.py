"""Quotation PDF. Pure rendering: it prints the numbers it is given and calculates nothing.

Amounts print as "Rs. 1,652.00" rather than with the rupee sign, because the built-in PDF fonts
have no such glyph and shipping a font file would add a dependency for no gain (DECISIONS.md).
"""

import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.pricing.engine import Totals
from app.pricing.inr import amount_in_words, format_inr


@dataclass(frozen=True)
class PdfLine:
    description: str
    hsn_sac: str | None
    qty: Decimal
    unit: str
    unit_price_paise: int
    discount_paise: int
    gst_rate: int
    line_total_paise: int


@dataclass(frozen=True)
class QuotePdf:
    seller_name: str
    seller_gstin: str | None
    seller_address: str | None
    seller_phone: str | None
    seller_state: str | None
    buyer_name: str | None
    buyer_phone: str | None
    buyer_state: str | None
    quote_number: str
    issued_on: date
    valid_until: date
    lines: list[PdfLine]
    totals: Totals
    terms: str | None


def _money(paise: int) -> str:
    return format_inr(paise).replace("₹", "Rs. ")


def _qty(value: Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _p(text: str | None, style: ParagraphStyle) -> Paragraph:
    # Paragraph parses markup, so everything that came from a customer or owner is escaped.
    return Paragraph(escape(text or ""), style)


class _Styles:
    def __init__(self) -> None:
        base = getSampleStyleSheet()
        self.small = ParagraphStyle("small", parent=base["Normal"], fontSize=8.5, leading=11)
        self.bold = ParagraphStyle("bold", parent=self.small, fontName="Helvetica-Bold")
        self.title = ParagraphStyle("title", parent=base["Title"], fontSize=18, alignment=0)


def _header(data: QuotePdf, st: _Styles) -> list[object]:
    seller = [_p(data.seller_name, st.bold)]
    if data.seller_gstin:
        seller.append(_p(f"GSTIN: {data.seller_gstin}", st.small))
    if data.seller_address:
        seller.append(_p(data.seller_address, st.small))
    if data.seller_phone:
        seller.append(_p(f"Phone: {data.seller_phone}", st.small))
    meta = [
        _p(f"Quotation no: {data.quote_number}", st.bold),
        _p(f"Date: {data.issued_on:%d %b %Y}", st.small),
        _p(f"Valid until: {data.valid_until:%d %b %Y}", st.small),
    ]
    buyer = [_p("Quotation for", st.small), _p(data.buyer_name or "Customer", st.bold)]
    if data.buyer_phone:
        buyer.append(_p(f"Phone: {data.buyer_phone}", st.small))
    header = Table([[seller, meta], [buyer, ""]], colWidths=[105 * mm, 75 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return [header, Spacer(1, 6 * mm)]


def _lines_table(data: QuotePdf, st: _Styles) -> list[object]:
    rows: list[list[object]] = [
        [
            _p(h, st.bold)
            for h in ("#", "Description", "HSN/SAC", "Qty", "Rate", "Disc.", "GST", "Amount")
        ]
    ]
    for number, line in enumerate(data.lines, start=1):
        rows.append(
            [
                _p(str(number), st.small),
                _p(line.description, st.small),
                _p(line.hsn_sac, st.small),
                _p(f"{_qty(line.qty)} {line.unit}", st.small),
                _p(_money(line.unit_price_paise), st.small),
                _p(_money(line.discount_paise) if line.discount_paise else "-", st.small),
                _p(f"{line.gst_rate}%", st.small),
                _p(_money(line.line_total_paise), st.small),
            ]
        )
    items = Table(
        rows,
        colWidths=[8 * mm, 56 * mm, 18 * mm, 24 * mm, 22 * mm, 16 * mm, 11 * mm, 25 * mm],
        repeatRows=1,
    )
    items.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return [items, Spacer(1, 5 * mm)]


def _totals(data: QuotePdf, st: _Styles) -> list[object]:
    t = data.totals
    tax_rows: list[list[object]] = [
        [_p(h, st.bold) for h in ("GST rate", "Taxable", "CGST", "SGST", "IGST")]
    ]
    for group in t.groups:
        tax_rows.append(
            [
                _p(f"{group.gst_rate}%", st.small),
                _p(_money(group.taxable_paise), st.small),
                _p(_money(group.cgst_paise), st.small),
                _p(_money(group.sgst_paise), st.small),
                _p(_money(group.igst_paise), st.small),
            ]
        )
    tax = Table(tax_rows, colWidths=[22 * mm, 32 * mm, 28 * mm, 28 * mm, 28 * mm])
    tax.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey)]))

    summary: list[list[object]] = [
        [_p("Subtotal", st.small), _p(_money(t.subtotal_paise), st.small)],
        [_p("Discount", st.small), _p(f"- {_money(t.discount_paise)}", st.small)],
        [_p("Taxable amount", st.small), _p(_money(t.taxable_paise), st.small)],
        [_p("CGST", st.small), _p(_money(t.cgst_paise), st.small)],
        [_p("SGST", st.small), _p(_money(t.sgst_paise), st.small)],
        [_p("IGST", st.small), _p(_money(t.igst_paise), st.small)],
        [_p("Round off", st.small), _p(_money(t.round_off_paise), st.small)],
        [_p("Total", st.bold), _p(_money(t.total_paise), st.bold)],
    ]
    totals_table = Table(summary, colWidths=[40 * mm, 35 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]))
    return [
        tax,
        Spacer(1, 4 * mm),
        totals_table,
        Spacer(1, 3 * mm),
        _p(amount_in_words(t.total_paise), st.bold),
    ]


def _footer(data: QuotePdf, st: _Styles) -> list[object]:
    story: list[object] = []
    if data.terms:
        story += [Spacer(1, 6 * mm), _p("Terms and conditions", st.bold), _p(data.terms, st.small)]
    story += [
        Spacer(1, 8 * mm),
        _p("This is a computer-generated quotation and needs no signature.", st.small),
    ]
    return story


def render_quote_pdf(data: QuotePdf) -> bytes:
    st = _Styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Quotation {data.quote_number}",
    )
    story = [
        _p("QUOTATION", st.title),
        *_header(data, st),
        *_lines_table(data, st),
        *_totals(data, st),
        *_footer(data, st),
    ]
    doc.build(story)
    return buffer.getvalue()
