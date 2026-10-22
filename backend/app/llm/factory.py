from collections.abc import Callable

from app.core.config import Settings
from app.llm import FakeEmbedder, FakeLLM, LLMClient, OpenAICompatibleLLM
from app.llm.client import RunRecorder
from app.llm.types import LLMRequest, LLMResponse
from app.schemas.catalog import ColumnBinding, MappingOutput


def demo_response(request: LLMRequest) -> LLMResponse:
    if request.agent == "column_mapper":
        headers = request.content.model_dump()["headers"]
        names = {
            "sku": ["sku", "code", "product code"],
            "name": ["name", "product", "product name"],
            "price": ["price", "rate", "amount", "unit price"],
            "gst_rate": ["gst_rate", "gst", "tax"],
            "category": ["category"],
            "description": ["description"],
            "unit": ["unit"],
            "aliases": ["aliases"],
            "hsn_sac": ["hsn_sac"],
            "stock_status": ["stock_status"],
        }
        bindings = [
            ColumnBinding(field=field, column=header)
            for field, aliases in names.items()
            for header in headers
            if header.lower().strip() in aliases
        ]
        return LLMResponse(output=MappingOutput(bindings=bindings).model_dump())
    raise ValueError("No offline demo fixture for this agent")


def make_llm(
    settings: Settings,
    recorder: RunRecorder,
    fallback: Callable[[LLMRequest], LLMResponse] = demo_response,
) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLM(recorder, {}, fallback=fallback)
    return OpenAICompatibleLLM(recorder, settings)


def make_embedder(settings: Settings) -> FakeEmbedder:
    if settings.embedding_provider != "fake":
        raise ValueError("Configure a supported embedding provider")
    return FakeEmbedder(settings.embedding_dim)
