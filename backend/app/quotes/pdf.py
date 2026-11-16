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


def render_quote_pdf(data: QuotePdf) -> bytes:
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, leading=11)
    bold = ParagraphStyle("bold", parent=small, fontName="Helvetica-Bold")
    title = ParagraphStyle("title", parent=styles["Title"], fontSize=18, alignment=0)
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
    story: list[object] = [_p("QUOTATION", title)]

    seller = [_p(data.seller_name, bold)]
    if data.seller_gstin:
        seller.append(_p(f"GSTIN: {data.seller_gstin}", small))
    if data.seller_address:
        seller.append(_p(data.seller_address, small))
    if data.seller_phone:
        seller.append(_p(f"Phone: {data.seller_phone}", small))
    meta = [
        _p(f"Quotation no: {data.quote_number}", bold),
        _p(f"Date: {data.issued_on:%d %b %Y}", small),
        _p(f"Valid until: {data.valid_until:%d %b %Y}", small),
    ]
    buyer = [_p("Quotation for", small), _p(data.buyer_name or "Customer", bold)]
    if data.buyer_phone:
        buyer.append(_p(f"Phone: {data.buyer_phone}", small))
    header = Table([[seller, meta], [buyer, ""]], colWidths=[105 * mm, 75 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [header, Spacer(1, 6 * mm)]

    rows: list[list[object]] = [
        [
            _p(h, bold)
            for h in ("#", "Description", "HSN/SAC", "Qty", "Rate", "Disc.", "GST", "Amount")
        ]
    ]
    for number, line in enumerate(data.lines, start=1):
        rows.append(
            [
                _p(str(number), small),
                _p(line.description, small),
                _p(line.hsn_sac, small),
                _p(f"{_qty(line.qty)} {line.unit}", small),
                _p(_money(line.unit_price_paise), small),
                _p(_money(line.discount_paise) if line.discount_paise else "-", small),
                _p(f"{line.gst_rate}%", small),
                _p(_money(line.line_total_paise), small),
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
    story += [items, Spacer(1, 5 * mm)]

    t = data.totals
    tax_rows: list[list[object]] = [
        [_p(h, bold) for h in ("GST rate", "Taxable", "CGST", "SGST", "IGST")]
    ]
    for group in t.groups:
        tax_rows.append(
            [
                _p(f"{group.gst_rate}%", small),
                _p(_money(group.taxable_paise), small),
                _p(_money(group.cgst_paise), small),
                _p(_money(group.sgst_paise), small),
                _p(_money(group.igst_paise), small),
            ]
        )
    tax = Table(tax_rows, colWidths=[22 * mm, 32 * mm, 28 * mm, 28 * mm, 28 * mm])
    tax.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey)]))
    story += [tax, Spacer(1, 4 * mm)]

    summary: list[list[object]] = [
        [_p("Subtotal", small), _p(_money(t.subtotal_paise), small)],
        [_p("Discount", small), _p(f"- {_money(t.discount_paise)}", small)],
        [_p("Taxable amount", small), _p(_money(t.taxable_paise), small)],
        [_p("CGST", small), _p(_money(t.cgst_paise), small)],
        [_p("SGST", small), _p(_money(t.sgst_paise), small)],
        [_p("IGST", small), _p(_money(t.igst_paise), small)],
        [_p("Round off", small), _p(_money(t.round_off_paise), small)],
        [_p("Total", bold), _p(_money(t.total_paise), bold)],
    ]
    totals_table = Table(summary, colWidths=[40 * mm, 35 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]))
    story += [totals_table, Spacer(1, 3 * mm), _p(amount_in_words(t.total_paise), bold)]

    if data.terms:
        story += [Spacer(1, 6 * mm), _p("Terms and conditions", bold), _p(data.terms, small)]
    story += [
        Spacer(1, 8 * mm),
        _p("This is a computer-generated quotation and needs no signature.", small),
    ]
    doc.build(story)
    return buffer.getvalue()
