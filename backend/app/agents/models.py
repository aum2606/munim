"""Typed inputs and outputs of the agents (AGENTS.md: every agent I/O is a Pydantic model)."""

import enum
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.tools.business_info import BusinessInfo

Language = Literal["en", "hi", "gu", "hinglish", "gujlish", "other"]
Script = Literal["latin", "devanagari", "gujarati", "other"]


class Intent(enum.StrEnum):
    GREETING = "greeting"
    PRODUCT_INFO = "product_info"
    AVAILABILITY = "availability"
    PRICING = "pricing"
    QUOTE_REQUEST = "quote_request"
    POLICY = "policy"
    GENERAL_FAQ = "general_faq"
    ORDER_FOLLOWUP = "order_followup"
    COMPLAINT = "complaint"
    HUMAN_REQUEST = "human_request"
    NEGOTIATION = "negotiation"
    SPAM = "spam"
    OFF_TOPIC = "off_topic"


class Turn(BaseModel):
    role: Literal["customer", "assistant"]
    text: str


class RouterInput(BaseModel):
    business_type: str
    turns: list[Turn]  # oldest first; the last customer turn(s) are what to classify
    quote_flow_active: bool = False


class RouterOutput(BaseModel):
    intent: Intent
    secondary_intents: list[Intent] = Field(default_factory=list)
    language: Language = "en"
    script: Script = "latin"
    entities: dict[str, str] = Field(default_factory=dict)
    mentioned_catalog_terms: list[str] = Field(default_factory=list)
    # The question restated in plain English, only used to search the shop's FAQs: the embedding
    # model finds Hindi and Gujarati script questions far less often than English ones.
    search_query_en: str = Field(default="", max_length=300)
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    confidence: float = Field(ge=0, le=1)


class ChunkEvidence(BaseModel):
    chunk_id: uuid.UUID
    title: str
    content: str


class ItemEvidence(BaseModel):
    item_id: uuid.UUID
    sku: str
    name: str
    unit: str
    price: str  # already formatted from catalogue paise, e.g. "₹250.00"
    gst_rate: int
    stock_status: str
    description: str | None


class KnowledgeInput(BaseModel):
    question: str
    turns: list[Turn]
    router: RouterOutput
    business: BusinessInfo
    chunks: list[ChunkEvidence]
    items: list[ItemEvidence]


class KnowledgeAnswer(BaseModel):
    answer_points: list[str] = Field(default_factory=list)
    cited_chunk_ids: list[uuid.UUID] = Field(default_factory=list)
    cited_item_ids: list[uuid.UUID] = Field(default_factory=list)
    price_item_ids: list[uuid.UUID] = Field(default_factory=list)  # items whose price to show
    grounded: bool
    gap_question: str | None = None


class ResponderInput(BaseModel):
    language: Language
    script: Script
    tone: str
    channel: str
    max_chars: int
    answer_points: list[str]
    price_lines: list[str]  # built by code from the catalogue; must appear verbatim
    violation_feedback: str | None = None


class ResponderOutput(BaseModel):
    reply: str


class SlotSchema(BaseModel):
    """One question a quote needs answered, as shown to the model."""

    name: str
    type: str
    description: str = ""
    options: list[str] = Field(default_factory=list)
    required: bool = False
    hint: str = ""


class CategoryView(BaseModel):
    category: str
    slots: list[SlotSchema]


class RequirementsInput(BaseModel):
    categories: list[CategoryView]
    category: str | None  # already chosen earlier in the conversation
    filled: dict[str, Any]
    turns: list[Turn]


class RequirementsOutput(BaseModel):
    category: str | None = None
    filled: dict[str, Any] = Field(default_factory=dict)  # only what the customer actually said
    unknown_slots: list[str] = Field(default_factory=list)  # the customer said they don't know
    questions: list[str] = Field(default_factory=list)


class AddonView(BaseModel):
    code: str
    name: str


class CandidateItem(BaseModel):
    sku: str
    name: str
    unit: str
    aliases: list[str]
    addons: list[AddonView]


class MappingInput(BaseModel):
    category: str
    requirements: dict[str, Any]
    candidates: list[CandidateItem]


class ProposedLineOut(BaseModel):
    sku: str | None = None  # a SKU from the candidate list, or null if nothing matches
    description: str = ""
    quantity: str | int | float = 1  # pieces as the customer said it; never a price
    width: str | int | float | None = None
    height: str | int | float | None = None
    addon_codes: list[str] = Field(default_factory=list)


class MappingOutput(BaseModel):
    lines: list[ProposedLineOut] = Field(default_factory=list)
    unmapped: list[str] = Field(default_factory=list)
