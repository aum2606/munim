from collections import deque

from app.llm.base import ChatMessage, LLMClient, LLMResult, Slot


class FakeLLM(LLMClient):
    """Scripted replies, returned in order. Tests never call a real model."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = deque(replies)
        self.calls: list[tuple[Slot, list[ChatMessage]]] = []

    def add(self, *replies: str) -> None:
        self._replies.extend(replies)

    async def complete(
        self, slot: Slot, messages: list[ChatMessage], *, json_mode: bool = False
    ) -> LLMResult:
        self.calls.append((slot, list(messages)))
        if not self._replies:
            raise AssertionError("FakeLLM has no scripted reply left")
        return LLMResult(
            text=self._replies.popleft(),
            provider="fake",
            model="fake-1",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=1,
        )
