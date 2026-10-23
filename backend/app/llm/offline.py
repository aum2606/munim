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
    if request.agent == "requirements":
        from app.schemas.requirements import RequirementsOutput, SlotUpdate

        question = body["question"]
        values = dict(re.findall(r"(\w+)\s*[:=]\s*([^;\n]+)", question))
        values = {key: value.strip() for key, value in values.items() if key in body["slots"]}
        if not values:
            parts = [part.strip() for part in question.split(";")]
            if body["awaiting"]:
                for key, value in zip(body["awaiting"], parts, strict=False):
                    values[key] = value
        return LLMResponse(
            output=RequirementsOutput(
                updates=[SlotUpdate(key=key, value=value) for key, value in values.items()]
            ).model_dump()
        )
    if request.agent == "quotation":
        from decimal import Decimal

        from app.schemas.quotes import ProposedLine, QuotationOutput

        requirements = {entry["key"]: entry["value"] for entry in body["requirements"]}
        text = " ".join(
            requirements.get(key, "") for key in ("item", "product", "event_type", "deliverables")
        ).lower()
        tokens = set(re.findall(r"[a-z]+", text))
        candidates = body["candidates"]
        ranked = sorted(
            candidates,
            key=lambda candidate: len(
                tokens
                & set(
                    re.findall(
                        r"[a-z]+", " ".join([candidate["name"], *candidate["aliases"]]).lower()
                    )
                )
            ),
            reverse=True,
        )
        selected = (
            ranked[0]
            if ranked
            and tokens
            & set(
                re.findall(r"[a-z]+", " ".join([ranked[0]["name"], *ranked[0]["aliases"]]).lower())
            )
            else None
        )
        if selected is None:
            return LLMResponse(
                output=QuotationOutput(lines=[], unmapped_requirements=["product"]).model_dump()
            )
        attributes = {entry["key"]: entry["value"] for entry in selected["attributes"]}
        qty = Decimal(requirements.get("quantity", requirements.get("days", "1"))) / Decimal(
            attributes.get("pack_size", "1")
        )
        return LLMResponse(
            output=QuotationOutput(
                lines=[ProposedLine(sku=selected["sku"], qty=format(qty, "f"), options=[])],
                unmapped_requirements=[],
            ).model_dump()
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
