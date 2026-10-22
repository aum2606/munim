from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.schemas.knowledge import Fact, PriceRef, StrictModel


class Intent(StrEnum):
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


class AgentMessage(StrictModel):
    direction: Literal["in", "out"]
    content: str


class RouterInput(StrictModel):
    messages: list[AgentMessage]
    business_type: str


class Entities(StrictModel):
    product: str | None
    quantity: str | None
    date: str | None


class RouterOutput(StrictModel):
    intent: Intent
    secondary_intents: list[Intent]
    language: Literal["en", "hi", "gu", "hinglish", "gujlish", "other"]
    script: Literal["latin", "devanagari", "gujarati", "other"]
    entities: Entities
    mentioned_catalog_terms: list[str]
    sentiment: Literal["positive", "neutral", "negative"]
    confidence: float = Field(ge=0, le=1)


class KnowledgeInput(StrictModel):
    question: str
    facts: list[Fact]


class KnowledgeAnswer(StrictModel):
    answer_points: list[str]
    citations: list[str]
    prices: list[PriceRef]
    grounded: bool
    gap_question: str | None


class ResponderInput(StrictModel):
    question: str
    language: str
    tone: str
    trusted_messages: list[str]
    violation: str | None


class ResponderOutput(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
