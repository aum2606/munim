"""Demo businesses. Every name, price and policy here is invented for demos and tests.
GST rates are illustrative: check current rates before using any of this for real invoices."""

from dataclasses import dataclass, field, replace
from typing import Any

from app.db.models import StockStatus
from app.repositories.catalog import CatalogRow


@dataclass(frozen=True)
class RuleSeed:
    sku: str  # the catalogue item the rule belongs to
    rule_type: str  # qty_tier | addon | min_order
    params: dict[str, Any]


@dataclass(frozen=True)
class SchemaSeed:
    category: str
    json_schema: dict[str, Any]
    defaults: dict[str, Any]
    question_hints: dict[str, str]


@dataclass(frozen=True)
class DemoBusiness:
    key: str
    name: str
    business_type: str
    owner_email: str
    items: list[CatalogRow]
    faqs: list[tuple[str, str]]
    rules: list[RuleSeed] = field(default_factory=list)
    schemas: list[SchemaSeed] = field(default_factory=list)
    # Invented, but GSTIN-shaped so the profile validators and quote PDFs can be shown off.
    gstin: str = "24ABCDE1234F1Z5"
    address: str = "Shop 12, Ring Road, Surat, Gujarat 395002"
    phone: str = "+91 90000 00001"
    quote_terms: str = (
        "50 percent advance with the order, balance before delivery. "
        "Prices are valid until the date shown. GST is extra as shown."
    )


def _item(
    sku: str,
    name: str,
    rupees: int,
    unit: str,
    aliases: list[str],
    category: str,
    description: str = "",
    gst: int = 18,
    hsn: str = "4911",
) -> CatalogRow:
    return CatalogRow(
        sku=sku,
        name=name,
        base_price_paise=rupees * 100,
        unit=unit,
        aliases=aliases,
        category=category,
        description=description or None,
        gst_rate=gst,
        hsn_sac=hsn,
        stock_status=StockStatus.IN_STOCK,
    )


PRINTING = DemoBusiness(
    key="printing",
    name="Shree Ganesh Printing Press",
    business_type="printing press",
    owner_email="demo-printing@example.com",
    items=[
        _item(
            "VC-STD",
            "Visiting card (100 pcs)",
            250,
            "per 100",
            ["business card", "name card", "visiting cards"],
            "Cards",
            "300 gsm art card, matt finish, 2 sides",
        ),
        _item(
            "VC-PREM",
            "Premium visiting card (100 pcs)",
            450,
            "per 100",
            ["premium business card", "textured card"],
            "Cards",
            "350 gsm textured card, spot UV",
        ),
        _item(
            "FLEX-STD",
            "Flex banner",
            18,
            "per sq ft",
            ["flex", "flex printing", "hoarding"],
            "Banners",
            "Normal flex with eyelets",
        ),
        _item(
            "FLEX-STAR",
            "Star flex banner",
            28,
            "per sq ft",
            ["star flex", "premium flex"],
            "Banners",
            "Higher quality star flex, outdoor use",
        ),
        _item(
            "BRO-A4",
            "Brochure A4 (100 pcs)",
            1800,
            "per 100",
            ["pamphlet a4", "brochure", "leaflet"],
            "Brochures",
            "A4, 130 gsm gloss, both sides, full colour",
        ),
        _item(
            "BRO-A5",
            "Brochure A5 (100 pcs)",
            1100,
            "per 100",
            ["pamphlet a5", "flyer"],
            "Brochures",
            "A5, 130 gsm gloss, both sides",
        ),
        _item(
            "STK-RND",
            "Round sticker (100 pcs)",
            600,
            "per 100",
            ["sticker", "label sticker", "round label"],
            "Stickers",
            "Vinyl, waterproof, 2 inch",
        ),
        _item(
            "LH-A4",
            "Letterhead A4 (100 pcs)",
            700,
            "per 100",
            ["letter head", "company letterhead"],
            "Stationery",
            "A4, 100 gsm maplitho, one colour",
        ),
        _item(
            "BILL-50",
            "Bill book (50 sets)",
            900,
            "per book",
            ["invoice book", "receipt book", "bill books"],
            "Stationery",
            "Duplicate, numbered, carbonless",
        ),
        _item(
            "ENV-DL",
            "Envelope DL (100 pcs)",
            650,
            "per 100",
            ["envelope", "printed envelope"],
            "Stationery",
            "DL size, 100 gsm, one colour print",
        ),
        _item(
            "ID-CARD",
            "PVC ID card",
            60,
            "per card",
            ["id card", "identity card", "employee card"],
            "Cards",
            "PVC, both sides, with lanyard",
        ),
        _item(
            "MUG-PRT",
            "Printed mug",
            220,
            "per mug",
            ["photo mug", "coffee mug", "custom mug"],
            "Gifts",
            "White ceramic, full wrap print",
        ),
        _item(
            "TSH-PRT",
            "Printed t-shirt",
            350,
            "per piece",
            ["t shirt", "tshirt printing", "custom tshirt"],
            "Gifts",
            "Cotton, single colour front print",
            hsn="6109",
        ),
        _item(
            "STAND-6X2",
            "Standee 6x2 ft",
            1500,
            "per piece",
            ["roll up standee", "standee"],
            "Banners",
            "Roll-up standee with printed flex",
        ),
        _item(
            "CAL-DESK",
            "Desk calendar (50 pcs)",
            2500,
            "per 50",
            ["calendar", "table calendar"],
            "Gifts",
            "12 pages, spiral bound",
        ),
    ],
    faqs=[
        (
            "What are your working hours?",
            "We are open Monday to Saturday, 10 am to 7 pm. Closed on Sundays.",
        ),
        (
            "Do you deliver?",
            "Yes, we deliver within Surat. Delivery is free for orders above 2000 rupees.",
        ),
        (
            "How long does printing take?",
            "Visiting cards take 2 working days. Brochures and stationery take 3 to 4 working days. Flex banners take 1 day.",
        ),
        (
            "What file formats do you accept?",
            "Please send your design as a PDF, CorelDRAW, Photoshop or high-resolution JPG file. We can also design it for you.",
        ),
        (
            "Do you charge for design?",
            "Basic design is free with an order. Custom logo design is charged separately and quoted by the team.",
        ),
        (
            "What is your payment policy?",
            "50 percent advance with the order and the balance before delivery. We accept UPI, bank transfer and cash.",
        ),
        (
            "Do you give a GST invoice?",
            "Yes, we give a GST invoice for every order. Please share your GSTIN when ordering.",
        ),
        (
            "Can I get a sample before a big order?",
            "Yes, we can print a single sample for a small charge. It is adjusted in the final bill.",
        ),
        (
            "What is the minimum order?",
            "Visiting cards start from 100 pieces. Stickers start from 100 pieces. Flex banners have no minimum.",
        ),
        (
            "Where is your shop?",
            "Shop 12, Ring Road, Surat. Landmark: opposite the textile market.",
        ),
    ],
)

PRINTING_RULES = [
    # Visiting cards are priced per 100; 500 cards is 5 units.
    RuleSeed(
        "VC-STD",
        "qty_tier",
        {
            "tiers": [
                {"min_qty": "5", "unit_price_paise": 23500, "discount_pct": None},
                {"min_qty": "10", "unit_price_paise": 22000, "discount_pct": None},
            ]
        },
    ),
    RuleSeed(
        "VC-STD",
        "addon",
        {"code": "LAM-MATT", "name": "Matt lamination", "price_paise": 4500, "per_unit": True},
    ),
    RuleSeed(
        "VC-STD",
        "addon",
        {"code": "LAM-GLOSS", "name": "Gloss lamination", "price_paise": 4500, "per_unit": True},
    ),
    RuleSeed("VC-STD", "min_order", {"min_qty": "1"}),
    RuleSeed(
        "FLEX-STD",
        "qty_tier",
        {"tiers": [{"min_qty": "100", "unit_price_paise": 1600, "discount_pct": None}]},
    ),
    RuleSeed(
        "FLEX-STD",
        "addon",
        {
            "code": "EYELETS",
            "name": "Eyelets and stitching",
            "price_paise": 10000,
            "per_unit": False,
        },
    ),
    RuleSeed(
        "BRO-A4",
        "qty_tier",
        {"tiers": [{"min_qty": "10", "unit_price_paise": None, "discount_pct": "10"}]},
    ),
    RuleSeed(
        "BRO-A4",
        "addon",
        {"code": "FOLD", "name": "Folding", "price_paise": 20000, "per_unit": True},
    ),
]

PRINTING_SCHEMA = SchemaSeed(
    category="printing",
    json_schema={
        "properties": {
            "item_type": {
                "type": "string",
                "description": "what to print, e.g. visiting card, flex banner, brochure",
            },
            "quantity": {"type": "integer", "description": "how many pieces"},
            "size": {
                "type": "string",
                "description": "size or dimensions; for flex banners width x height in feet",
            },
            "sides": {"type": "string", "enum": ["single", "double"]},
            "finishing": {
                "type": "string",
                "enum": ["none", "matt lamination", "gloss lamination"],
            },
            "deadline": {"type": "string", "description": "when they need it"},
        },
        "required": ["item_type", "quantity"],
    },
    defaults={"size": "standard", "sides": "double", "finishing": "none"},
    question_hints={
        "item_type": "What would you like to print?",
        "quantity": "How many pieces do you need?",
        "size": "What size do you need?",
        "finishing": "Do you want lamination (matt or gloss)?",
        "deadline": "By when do you need it?",
    },
)

PRINTING = replace(PRINTING, rules=PRINTING_RULES, schemas=[PRINTING_SCHEMA])

PHOTOGRAPHER = DemoBusiness(
    key="photographer",
    name="Moments by Meera Photography",
    business_type="wedding photographer",
    owner_email="demo-photographer@example.com",
    items=[
        _item(
            "WED-1D",
            "Wedding photography, 1 day",
            45000,
            "per day",
            ["wedding photographer", "wedding photos", "shaadi photography"],
            "Wedding",
            "1 photographer, up to 8 hours, 300 edited photos",
            hsn="998389",
        ),
        _item(
            "WED-2D",
            "Wedding photography, 2 days",
            80000,
            "per 2 days",
            ["2 day wedding", "wedding two days"],
            "Wedding",
            "2 photographers, 2 days, 600 edited photos",
            hsn="998389",
        ),
        _item(
            "WED-VID",
            "Wedding video add-on",
            30000,
            "per event",
            ["wedding video", "videography", "shaadi video"],
            "Wedding",
            "Cinematic highlight film, 4 to 6 minutes",
            hsn="998389",
        ),
        _item(
            "PRE-WED",
            "Pre-wedding shoot",
            25000,
            "per shoot",
            ["pre wedding", "prewedding shoot", "couple shoot"],
            "Wedding",
            "One location in Surat, 4 hours, 40 edited photos",
            hsn="998389",
        ),
        _item(
            "ALBUM-30",
            "Photo album, 30 sheets",
            8000,
            "per album",
            ["album", "wedding album", "photo book"],
            "Wedding",
            "30 sheets, hard cover, premium paper",
            hsn="4911",
        ),
        _item(
            "DRONE",
            "Drone coverage",
            8000,
            "per event",
            ["drone shoot", "drone photography"],
            "Add-ons",
            "Aerial photos and video of the venue",
            hsn="998389",
        ),
        _item(
            "MATERN",
            "Maternity shoot",
            12000,
            "per shoot",
            ["maternity photography", "baby bump shoot"],
            "Portraits",
            "Studio or outdoor, 2 hours, 25 edited photos",
            hsn="998389",
        ),
        _item(
            "BDAY",
            "Birthday event coverage",
            9000,
            "per event",
            ["birthday photography", "birthday shoot"],
            "Events",
            "Up to 3 hours, 100 edited photos",
            hsn="998389",
        ),
        _item(
            "PORTFOLIO",
            "Portfolio shoot",
            6000,
            "per shoot",
            ["model portfolio", "profile shoot"],
            "Portraits",
            "Studio, 2 outfits, 20 edited photos",
            hsn="998389",
        ),
        _item(
            "PRODUCT",
            "Product photography",
            500,
            "per product",
            ["product shoot", "catalogue photography"],
            "Commercial",
            "White background, 3 angles per product",
            hsn="998389",
        ),
    ],
    faqs=[
        (
            "How do I book a date?",
            "Pay a 25 percent advance to block your date. The balance is due before the event.",
        ),
        (
            "Do you travel outside Surat?",
            "Yes. Travel and stay outside Surat are charged extra and quoted by the team.",
        ),
        (
            "How long to get the photos?",
            "Edited photos are delivered in 3 weeks. Albums take 5 to 6 weeks.",
        ),
        (
            "Do you give the raw files?",
            "We share all edited photos in a online gallery. Raw files are not shared.",
        ),
        (
            "What if it rains on the event day?",
            "We will shoot indoors or reschedule a pre-wedding shoot at no extra cost.",
        ),
        (
            "Can I see your portfolio?",
            "Yes, our recent work is on our Instagram page and we can share an album link on request.",
        ),
        (
            "How many photographers will come?",
            "The 1-day package has one photographer. The 2-day package has two.",
        ),
        (
            "Do you offer discounts?",
            "Packages have fixed prices. For custom bundles, the team will share a quotation.",
        ),
    ],
)

PHOTOGRAPHER_RULES = [
    RuleSeed(
        "WED-2D",
        "addon",
        {"code": "DRONE-ADD", "name": "Drone coverage", "price_paise": 800000, "per_unit": False},
    ),
    RuleSeed(
        "WED-1D",
        "addon",
        {"code": "DRONE-ADD", "name": "Drone coverage", "price_paise": 800000, "per_unit": False},
    ),
    RuleSeed(
        "PRODUCT",
        "qty_tier",
        {"tiers": [{"min_qty": "20", "unit_price_paise": 40000, "discount_pct": None}]},
    ),
]

PHOTOGRAPHER_SCHEMA = SchemaSeed(
    category="photography",
    json_schema={
        "properties": {
            "event_type": {
                "type": "string",
                "description": "wedding, pre-wedding shoot, birthday, maternity, portfolio, product",
            },
            "event_date": {"type": "string", "description": "date or month of the event"},
            "city": {"type": "string", "description": "where the event is"},
            "days": {"type": "integer", "description": "how many days of coverage"},
            "deliverables": {
                "type": "array",
                "items": {"enum": ["photos", "video", "album", "drone"]},
            },
        },
        "required": ["event_type", "event_date", "city"],
    },
    defaults={"days": 1, "deliverables": ["photos"]},
    question_hints={
        "event_type": "What kind of event is it?",
        "event_date": "What is the date of the event?",
        "city": "Which city is it in?",
        "days": "How many days do you need us for?",
        "deliverables": "Do you want photos, video, an album or drone coverage?",
    },
)

PHOTOGRAPHER = replace(PHOTOGRAPHER, rules=PHOTOGRAPHER_RULES, schemas=[PHOTOGRAPHER_SCHEMA])

BUSINESSES = {b.key: b for b in (PRINTING, PHOTOGRAPHER)}
