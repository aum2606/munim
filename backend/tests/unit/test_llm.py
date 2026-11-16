import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import LLMOutputError, LLMUnavailableError
from app.llm.base import ChatMessage
from app.llm.embedder import FakeEmbedder
from app.llm.fake import FakeLLM
from app.llm.openai_compat import (
    ChainLLMClient,
    ProviderSpec,
    _error_code,
    parse_chain,
    provider_keys,
)
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
    specs = parse_chain("a|https://x.example/v1/|m1, b|http://localhost:11434/v1|m2", {"a": "KEY"})
    assert [(s.name, s.base_url, s.model, s.api_key) for s in specs] == [
        ("a", "https://x.example/v1", "m1", "KEY"),
        ("b", "http://localhost:11434/v1", "m2", None),
    ]
    assert parse_chain("", {}) == []
    assert "KEY" not in repr(specs[0])


def test_a_known_provider_needs_only_its_name_and_a_model() -> None:
    (groq, router) = parse_chain("groq|llama-x, openrouter|vendor/model:free", {"groq": "G"})
    assert (groq.base_url, groq.model, groq.api_key) == (
        "https://api.groq.com/openai/v1",
        "llama-x",
        "G",
    )
    assert (router.base_url, router.model, router.api_key) == (
        "https://openrouter.ai/api/v1",
        "vendor/model:free",
        None,
    )


def test_each_provider_reads_its_own_key_variable() -> None:
    settings = Settings(
        _env_file=None,  # a developer's own .env must not leak into a test
        app_env="test",
        groq_api_key="G",
        OPEN_ROUTER_API_KEY="O",  # type: ignore[call-arg]  # the spelling used in .env
        llm_api_keys="groq=old,custom=C",
    )
    assert provider_keys(settings) == {"groq": "G", "openrouter": "O", "custom": "C"}
    assert Settings(_env_file=None, OPENROUTER_API_KEY="P").openrouter_api_key == "P"  # type: ignore[call-arg]


@pytest.mark.parametrize("bad", ["a|b", "a|ftp://x|m", "a||m", "mystery|model", "groq|"])
def test_parse_chain_rejects_malformed_entries(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_chain(bad, {})


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


def _ok() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})


async def test_a_short_rate_limit_waits_and_retries_the_same_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("app.llm.openai_compat.asyncio.sleep", fake_sleep)
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if len(hosts) == 1:
            return httpx.Response(429, headers={"retry-after": "2"})
        return _ok()

    result = await _chain(httpx.MockTransport(handler), "a", "b").complete("small", USER)
    assert (result.provider, hosts, waits) == ("a", ["a.test", "a.test"], [2.0])


@pytest.mark.parametrize("headers", [{}, {"retry-after": "soon"}, {"retry-after": "120"}])
async def test_a_long_or_unhinted_rate_limit_moves_on_without_waiting(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    async def never(_: float) -> None:
        raise AssertionError("should not wait")

    monkeypatch.setattr("app.llm.openai_compat.asyncio.sleep", never)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers=headers) if request.url.host == "a.test" else _ok()

    result = await _chain(httpx.MockTransport(handler), "a", "b").complete("small", USER)
    assert result.provider == "b"


async def test_a_provider_that_keeps_limiting_is_tried_three_times_then_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fast(_: float) -> None:
        return None

    monkeypatch.setattr("app.llm.openai_compat.asyncio.sleep", fast)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(429, headers={"retry-after": "1"})

    with pytest.raises(LLMUnavailableError):
        await _chain(httpx.MockTransport(handler), "a").complete("small", USER)
    assert calls == ["a.test"] * 3


def test_only_the_providers_short_error_code_is_read() -> None:
    body = {"error": {"code": "json_validate_failed", "message": "echoes: secret customer text"}}
    assert _error_code(httpx.Response(400, json=body)) == "json_validate_failed"
    assert _error_code(httpx.Response(400, json={"error": "plain string"})) is None
    assert _error_code(httpx.Response(502, text="<html>")) is None
    assert _error_code(None) is None


async def test_a_model_that_breaks_json_mode_is_asked_again_at_once() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
        return _ok()

    result = await _chain(httpx.MockTransport(handler), "a", "b").complete("small", USER)
    assert (result.provider, calls) == ("a", ["a.test", "a.test"])
    other = httpx.MockTransport(
        lambda r: (
            httpx.Response(400, json={"error": {"code": "invalid_request_error"}})
            if r.url.host == "a.test"
            else _ok()
        )
    )
    assert (
        await _chain(other, "a", "b").complete("small", USER)
    ).provider == "b"  # other 400s move on
