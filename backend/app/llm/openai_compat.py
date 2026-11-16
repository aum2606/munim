"""Provider fallback chain over any OpenAI-compatible /chat/completions endpoint.

Free tiers rate-limit and disappear, so each slot has an ordered chain (BUILD_PLAN.md section 3):
a failing provider falls through to the next, ending at a local model (e.g. Ollama) if configured.
"""

import asyncio
import time
from dataclasses import dataclass

import httpx
import structlog

from app.core.config import Settings
from app.core.errors import LLMUnavailableError
from app.llm.base import ChatMessage, LLMClient, LLMResult, Slot

log = structlog.get_logger()


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    model: str
    api_key: str | None = None

    def __repr__(self) -> str:  # never print the key
        return f"ProviderSpec({self.name}, {self.base_url}, {self.model})"


# Known OpenAI-compatible endpoints, so a chain entry can be just "groq|<model>".
# Checked against each provider's docs on 2026-11-16 (see .env.example).
KNOWN_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "ollama": "http://localhost:11434/v1",
}


def provider_keys(settings: Settings) -> dict[str, str]:
    """API key per provider name. GROQ_API_KEY and friends win over the older LLM_API_KEYS list."""
    keys = dict(pair.split("=", 1) for pair in settings.llm_api_keys.split(",") if "=" in pair)
    named = {
        "groq": settings.groq_api_key,
        "openrouter": settings.openrouter_api_key,
        "gemini": settings.gemini_api_key,
    }
    return {**keys, **{name: key for name, key in named.items() if key}}


def parse_chain(chain: str, keys: dict[str, str]) -> list[ProviderSpec]:
    """Comma-separated entries: "name|model" for a known provider, else "name|https://base|model"."""
    specs = []
    for entry in filter(None, (e.strip() for e in chain.split(","))):
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) == 2 and parts[0] in KNOWN_BASE_URLS:
            parts = [parts[0], KNOWN_BASE_URLS[parts[0]], parts[1]]
        if len(parts) != 3 or not all(parts) or not parts[1].startswith(("http://", "https://")):
            raise ValueError(
                "LLM chain entries must look like name|model (groq, openrouter, gemini, ollama) "
                "or name|https://base_url|model"
            )
        specs.append(ProviderSpec(parts[0], parts[1].rstrip("/"), parts[2], keys.get(parts[0])))
    return specs


MAX_RATE_LIMIT_WAIT_S = 30.0
MAX_ATTEMPTS = 3  # per provider; only a 429 with a short Retry-After earns another try


def _error_code(response: httpx.Response | None) -> str | None:
    """The provider's short error code (e.g. json_validate_failed). Never the message: it can echo
    the prompt."""
    if response is None:
        return None
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None
    return code[:60] if isinstance(code, str) else None


def _rate_limit_wait(response: httpx.Response | None) -> float | None:
    """Seconds to wait before trying the same provider again, or None to move on: a 429 with a
    short Retry-After, or a model that broke JSON mode (Groq's 400 json_validate_failed), which
    usually answers correctly the next time."""
    if response is None:
        return None
    if response.status_code == 400 and _error_code(response) == "json_validate_failed":
        return 0.0
    if response.status_code != 429:
        return None
    try:
        wait = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None  # no hint: fall through to the next provider at once
    return wait if 0 <= wait <= MAX_RATE_LIMIT_WAIT_S else None


class ChainLLMClient(LLMClient):
    def __init__(
        self,
        chains: dict[Slot, list[ProviderSpec]],
        http: httpx.AsyncClient,
        timeout_s: float = 30.0,
    ) -> None:
        self._chains = chains
        self._http = http
        self._timeout = timeout_s

    @classmethod
    def from_settings(cls, settings: Settings, http: httpx.AsyncClient) -> "ChainLLMClient":
        keys = provider_keys(settings)
        chains: dict[Slot, list[ProviderSpec]] = {
            "small": parse_chain(settings.llm_small_chain, keys),
            "large": parse_chain(settings.llm_large_chain, keys),
        }
        return cls(chains, http, settings.llm_timeout_s)

    async def complete(
        self, slot: Slot, messages: list[ChatMessage], *, json_mode: bool = False
    ) -> LLMResult:
        for spec in self._chains[slot]:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    return await self._call(spec, messages, json_mode)
                except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
                    # Provider, error class and HTTP status only; bodies may hold customer text.
                    response = exc.response if isinstance(exc, httpx.HTTPStatusError) else None
                    log.warning(
                        "llm_provider_failed",
                        provider=spec.name,
                        error=type(exc).__name__,
                        status=response.status_code if response else None,
                        code=_error_code(response),
                    )
                    wait = _rate_limit_wait(response)
                    if attempt < MAX_ATTEMPTS - 1 and wait is not None:
                        await asyncio.sleep(wait)  # a short free-tier limit: wait, don't give up
                        continue
                    break
        raise LLMUnavailableError("No language model is available right now")

    async def _call(
        self, spec: ProviderSpec, messages: list[ChatMessage], json_mode: bool
    ) -> LLMResult:
        body: dict[str, object] = {
            "model": spec.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": 0,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {spec.api_key}"} if spec.api_key else {}
        started = time.perf_counter()
        response = await self._http.post(
            f"{spec.base_url}/chat/completions", json=body, headers=headers, timeout=self._timeout
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        return LLMResult(
            text=data["choices"][0]["message"]["content"] or "",
            provider=spec.name,
            model=spec.model,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
