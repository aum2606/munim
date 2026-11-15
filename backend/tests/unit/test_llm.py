import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.errors import LLMOutputError, LLMUnavailableError
from app.llm.base import ChatMessage
from app.llm.embedder import FakeEmbedder
from app.llm.fake import FakeLLM
from app.llm.openai_compat import ChainLLMClient, ProviderSpec, parse_chain
from app.llm.transcriber import FakeTranscriber, Transcription


class Answer(BaseModel):
    intent: str
    confidence: float


USER = [ChatMessage(role="user", content="hello")]


async def test_structured_accepts_valid_json_and_fenced_json() -> None:
    llm = FakeLLM(['{"intent": "greeting", "confidence": 0.9}'])
    parsed, result = await llm.structured("small", USER, Answer)
    assert parsed.intent == "greeting" and result.provider == "fake"

    fenced = FakeLLM(['```json\n{"intent": "pricing", "confidence": 0.5}\n```'])
    assert (await fenced.structured("small", USER, Answer))[0].intent == "pricing"


async def test_structured_retries_once_with_the_error_fed_back() -> None:
    llm = FakeLLM(["not json at all", '{"intent": "pricing", "confidence": 0.8}'])
    parsed, result = await llm.structured("large", USER, Answer)
    assert parsed.intent == "pricing"
    assert len(llm.calls) == 2
    retry_prompt = llm.calls[1][1][-1].content
    assert "invalid" in retry_prompt and "not json at all" not in retry_prompt
    assert result.prompt_tokens == 20  # both attempts are counted


async def test_structured_gives_up_after_one_retry() -> None:
    llm = FakeLLM(["nope", '{"intent": 5}'])
    with pytest.raises(LLMOutputError):
        await llm.structured("small", USER, Answer)
    assert len(llm.calls) == 2


def test_parse_chain() -> None:
    specs = parse_chain("a|https://x.example/v1/|m1, b|http://localhost:11434/v1|m2", "a=KEY")
    assert [(s.name, s.base_url, s.model, s.api_key) for s in specs] == [
        ("a", "https://x.example/v1", "m1", "KEY"),
        ("b", "http://localhost:11434/v1", "m2", None),
    ]
    assert parse_chain("", "") == []
    assert "KEY" not in repr(specs[0])


@pytest.mark.parametrize("bad", ["a|b", "a|ftp://x|m", "a||m"])
def test_parse_chain_rejects_malformed_entries(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_chain(bad, "")


def _chain(handler: httpx.MockTransport, *names: str) -> ChainLLMClient:
    specs = [ProviderSpec(n, f"https://{n}.test/v1", f"{n}-model", f"key-{n}") for n in names]
    return ChainLLMClient({"small": specs, "large": []}, httpx.AsyncClient(transport=handler))


async def test_chain_falls_through_to_the_next_provider() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "a.test":
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    result = await _chain(httpx.MockTransport(handler), "a", "b").complete("small", USER)
    assert (result.text, result.provider, result.prompt_tokens) == ("hi", "b", 3)
    assert seen[1].headers["Authorization"] == "Bearer key-b"
    assert json.loads(seen[1].content)["model"] == "b-model"


async def test_chain_raises_when_every_provider_fails() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    with pytest.raises(LLMUnavailableError):
        await _chain(transport, "a", "b").complete("small", USER)
    with pytest.raises(LLMUnavailableError):  # an empty chain is also "unavailable"
        await _chain(transport).complete("small", USER)


async def test_chain_treats_malformed_response_as_provider_failure() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(LLMUnavailableError):
        await _chain(transport, "a").complete("small", USER)


async def test_fake_embedder_is_deterministic_and_normalised() -> None:
    embedder = FakeEmbedder(dim=16)
    first, again, other = await embedder.embed(["chai", "chai", "coffee"])
    assert first == again != other
    assert len(first) == 16 and abs(sum(x * x for x in first) - 1) < 1e-9


async def test_fake_transcriber_returns_scripted_results() -> None:
    result = Transcription("kal shop khuli hai?", "hi", 0.93)
    transcriber = FakeTranscriber([result])
    assert await transcriber.transcribe(b"audio", "audio/ogg") == result
    assert transcriber.calls == 1
