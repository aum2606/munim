from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.agents.guardrails import check_prices
from app.pricing.inr import amount_in_words, format_inr
from app.schemas.quotes import QuoteView


def quote_allowed_prices(quote: QuoteView) -> set[int]:
    amounts = {
        abs(value)
        for key, value in quote.totals.model_dump().items()
        if key != "tax_groups" and isinstance(value, int)
    }
    for group in quote.totals.tax_groups:
        amounts.update([group.taxable_paise, group.cgst_paise, group.sgst_paise, group.igst_paise])
    for line in quote.lines:
        amounts.update(
            [line.unit_price_paise, line.addon_paise, line.discount_paise, line.line_total_paise]
        )
    return amounts


def render_quote_pdf(quote: QuoteView, storage_root: Path) -> bytes:
    """Deterministic PDF from the persisted pricing-tool snapshot; never fetch remote assets.

    Layout API: https://docs.reportlab.com/reportlab/userguide/ch5_platypus/
    """
    font = "MunimNoto"
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont(font, str(Path(__file__).parent / "fonts/NotoSans-Regular.ttf"))
        )
        pdfmetrics.registerFontFamily(font, normal=font, bold=font, italic=font, boldItalic=font)
    normal = ParagraphStyle(
        "QuoteBody", fontName=font, fontSize=9, leading=14, textColor=colors.HexColor("#233047")
    )
    small = ParagraphStyle("QuoteSmall", parent=normal, fontSize=8, leading=12)
    heading = ParagraphStyle("QuoteHeading", parent=normal, fontSize=22, leading=28, spaceAfter=12)

    def paragraph(text: str, style: ParagraphStyle = normal) -> Paragraph:
        check_prices(text, quote_allowed_prices(quote))
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    stream = BytesIO()
    document = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=44,
        leftMargin=44,
        topMargin=40,
        bottomMargin=45,
        title=quote.quote_number,
        author=quote.seller.name,
    )
    story: list[Flowable] = [paragraph("QUOTATION", heading)]
    if quote.seller.logo_path:
        logo = (storage_root / quote.seller.logo_path).resolve()
        if logo.is_relative_to(storage_root.resolve()) and logo.is_file():
            story.append(Image(str(logo), width=90, height=48, kind="proportional", hAlign="LEFT"))
            story.append(Spacer(1, 10))
    environment = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        undefined=StrictUndefined,
        autoescape=True,
    )
    header = environment.get_template("quote_header.html.jinja").render(seller=quote.seller)
    check_prices(header, quote_allowed_prices(quote))
    issued = quote.created_at.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    valid_until = quote.valid_until.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    story.extend(
        [
            Paragraph(header, normal),
            Spacer(1, 14),
            paragraph(f"{quote.quote_number}  |  {quote.status.value.replace('_', ' ').title()}"),
            paragraph(f"Customer: {quote.customer_label}"),
            paragraph(
                "Place of supply state: "
                f"{quote.customer_state or quote.seller.state_code or 'Unspecified'}"
            ),
            paragraph(f"Issued: {issued}  |  Valid until: {valid_until}"),
            Spacer(1, 18),
        ]
    )
    rows = [
        [
            paragraph(value, small)
            for value in (
                "Description",
                "Qty / unit",
                "HSN/SAC",
                "GST",
                "Unit price",
                "Taxable value",
            )
        ]
    ]
    for line in quote.lines:
        description = line.description
        if line.addon_paise:
            description += "\nAdd-ons: " + format_inr(line.addon_paise)
        if line.discount_paise:
            description += "\nLine discount: " + format_inr(line.discount_paise)
        money = (
            "Owner pricing needed"
            if line.needs_owner_pricing
            else format_inr(line.line_total_paise)
        )
        values = (
            description,
            f"{line.qty.normalize():f}\n{line.unit}",
            line.hsn_sac or "-",
            f"{line.gst_rate}%",
            "-" if line.needs_owner_pricing else format_inr(line.unit_price_paise),
            money,
        )
        rows.append([paragraph(value, small) for value in values])
    table = Table(rows, colWidths=[155, 50, 55, 35, 100, 112], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#dbe3ed")),
            ]
        )
    )
    story.extend([table, Spacer(1, 20), paragraph("GST summary")])
    tax_rows = [[paragraph(value, small) for value in ("Rate", "Taxable", "CGST", "SGST", "IGST")]]
    for group in quote.totals.tax_groups:
        tax_rows.append(
            [
                paragraph(value, small)
                for value in (
                    f"{group.gst_rate}%",
                    format_inr(group.taxable_paise),
                    format_inr(group.cgst_paise),
                    format_inr(group.sgst_paise),
                    format_inr(group.igst_paise),
                )
            ]
        )
    tax_table = Table(tax_rows, colWidths=[47, 115, 115, 115, 115], repeatRows=1, hAlign="LEFT")
    tax_table.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)])
    )
    story.extend([tax_table, Spacer(1, 14)])
    for label, amount in (
        ("Subtotal", quote.totals.subtotal_paise),
        ("Discount", quote.totals.discount_paise),
        ("CGST", quote.totals.cgst_paise),
        ("SGST", quote.totals.sgst_paise),
        ("IGST", quote.totals.igst_paise),
    ):
        story.append(paragraph(label + ": " + format_inr(amount)))
    round_label = "Round-off (less)" if quote.totals.round_off_paise < 0 else "Round-off (add)"
    story.extend(
        [
            paragraph(round_label + ": " + format_inr(abs(quote.totals.round_off_paise))),
            Spacer(1, 8),
            paragraph("Total: " + format_inr(quote.totals.total_paise)),
            paragraph(amount_in_words(quote.totals.total_paise), small),
            Spacer(1, 20),
            paragraph("Terms"),
            paragraph(quote.terms, small),
            Spacer(1, 12),
            paragraph("This quotation is not a tax invoice.", small),
        ]
    )

    def footer(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(44, 25, quote.quote_number)
        canvas.drawRightString(A4[0] - 44, 25, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
