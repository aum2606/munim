import dataclasses
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import LLMOutputError

Slot = Literal["small", "large"]
T = TypeVar("T", bound=BaseModel)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LLMClient(ABC):
    """The only way application code talks to a model. Providers live behind this interface."""

    @abstractmethod
    async def complete(
        self, slot: Slot, messages: list[ChatMessage], *, json_mode: bool = False
    ) -> LLMResult: ...

    async def structured(
        self, slot: Slot, messages: list[ChatMessage], schema: type[T]
    ) -> tuple[T, LLMResult]:
        """Return output validated against `schema`; one retry that feeds the error back."""
        instruction = ChatMessage(
            role="system",
            content="Reply with a single JSON object matching this JSON Schema, and nothing "
            f"else:\n{json.dumps(schema.model_json_schema())}",
        )
        convo = [instruction, *messages]
        result = await self.complete(slot, convo, json_mode=True)
        try:
            return schema.model_validate_json(_FENCE.sub("", result.text.strip())), result
        except ValidationError as first_error:
            convo += [
                ChatMessage(role="assistant", content=result.text),
                ChatMessage(
                    role="user",
                    content="That reply was invalid: "
                    f"{_summarize(first_error)}. Return only the corrected JSON object.",
                ),
            ]
        retry = await self.complete(slot, convo, json_mode=True)
        merged = dataclasses.replace(
            retry,
            prompt_tokens=result.prompt_tokens + retry.prompt_tokens,
            completion_tokens=result.completion_tokens + retry.completion_tokens,
            latency_ms=result.latency_ms + retry.latency_ms,
        )
        try:
            return schema.model_validate_json(_FENCE.sub("", retry.text.strip())), merged
        except ValidationError as exc:
            raise LLMOutputError("Model output did not match the required schema") from exc


def _summarize(error: ValidationError) -> str:
    # Field paths and messages only: never echo model/customer text back into a prompt.
    return "; ".join(
        f"{'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}" for e in error.errors()
    )
