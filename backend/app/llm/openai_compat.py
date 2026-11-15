"""Provider fallback chain over any OpenAI-compatible /chat/completions endpoint.

Free tiers rate-limit and disappear, so each slot has an ordered chain (BUILD_PLAN.md section 3):
a failing provider falls through to the next, ending at a local model (e.g. Ollama) if configured.
"""

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


def parse_chain(chain: str, api_keys: str) -> list[ProviderSpec]:
    """chain: "name|base_url|model,name2|base_url2|model2"; api_keys: "name=key,name2=key2"."""
    keys = dict(pair.split("=", 1) for pair in api_keys.split(",") if "=" in pair)
    specs = []
    for entry in filter(None, (e.strip() for e in chain.split(","))):
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) != 3 or not all(parts) or not parts[1].startswith(("http://", "https://")):
            raise ValueError("LLM chain entries must look like name|https://base_url|model")
        specs.append(ProviderSpec(parts[0], parts[1].rstrip("/"), parts[2], keys.get(parts[0])))
    return specs


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
        chains: dict[Slot, list[ProviderSpec]] = {
            "small": parse_chain(settings.llm_small_chain, settings.llm_api_keys),
            "large": parse_chain(settings.llm_large_chain, settings.llm_api_keys),
        }
        return cls(chains, http, settings.llm_timeout_s)

    async def complete(
        self, slot: Slot, messages: list[ChatMessage], *, json_mode: bool = False
    ) -> LLMResult:
        for spec in self._chains[slot]:
            try:
                return await self._call(spec, messages, json_mode)
            except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
                # Log the provider and error class only; bodies may contain customer text.
                log.warning("llm_provider_failed", provider=spec.name, error=type(exc).__name__)
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
