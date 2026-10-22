import re
from typing import Literal

from app.llm.types import LLMRequest, LLMResponse
from app.schemas.agents import Entities, Intent, KnowledgeAnswer, ResponderOutput, RouterOutput
from app.schemas.knowledge import Fact


def agent_response(request: LLMRequest) -> LLMResponse:
    body = request.content.model_dump(mode="json")
    if request.agent == "router":
        text = body["messages"][-1]["content"].lower()
        hinglish = any(
            word in text.split()
            for word in ["bhai", "ka", "ki", "hai", "kya", "kitna", "kal", "chahiye"]
        )
        language: Literal["en", "hi", "gu", "hinglish", "gujlish", "other"] = (
            "hinglish" if hinglish else "en"
        )
        script: Literal["latin", "devanagari", "gujarati", "other"] = "latin"
        if re.search(r"[\u0900-\u097f]", text):
            language, script = "hi", "devanagari"
        elif re.search(r"[\u0a80-\u0aff]", text):
            language, script = "gu", "gujarati"
        intent = Intent.GENERAL_FAQ
        if any(term in text for term in ["complaint", "damaged", "angry"]):
            intent = Intent.COMPLAINT
        elif any(term in text for term in ["human", "owner", "agent please"]):
            intent = Intent.HUMAN_REQUEST
        elif any(term in text for term in ["ignore instructions", "discount", "system prompt"]):
            intent = Intent.NEGOTIATION
        elif any(term in text for term in ["quote", "quotation"]):
            intent = Intent.QUOTE_REQUEST
        elif any(term in text for term in ["price", "rate", "cost", "kitna"]):
            intent = Intent.PRICING
        elif any(term in text for term in ["available", "stock", "have a"]):
            intent = Intent.AVAILABILITY
        elif any(term in text for term in ["policy", "warranty", "refund", "delivery"]):
            intent = Intent.POLICY
        elif text.strip() in {"hello", "hi", "namaste", "namaste bhai"}:
            intent = Intent.GREETING
        elif any(term in text for term in ["football", "crypto"]):
            intent = Intent.OFF_TOPIC
        return LLMResponse(
            output=RouterOutput(
                intent=intent,
                secondary_intents=[],
                language=language,
                script=script,
                entities=Entities(product=None, quantity=None, date=None),
                mentioned_catalog_terms=[],
                sentiment="neutral",
                confidence=1,
            ).model_dump(mode="json")
        )
    if request.agent == "knowledge":
        facts = [Fact.model_validate(fact) for fact in body["facts"]]
        return LLMResponse(
            output=KnowledgeAnswer(
                answer_points=[fact.text for fact in facts],
                citations=[fact.ref for fact in facts],
                prices=[fact.price for fact in facts if fact.price is not None],
                grounded=bool(facts),
                gap_question=None if facts else body["question"],
            ).model_dump(mode="json")
        )
    if request.agent == "responder":
        return LLMResponse(output=ResponderOutput(text=body["trusted_messages"][0]).model_dump())
    raise ValueError("No offline demo response for this agent")
