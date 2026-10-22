import hashlib
import json
from collections import deque
from collections.abc import Callable, Sequence

from app.llm.client import LLMClient, RunRecorder
from app.llm.types import LLMRequest, LLMResponse


def input_hash(request: LLMRequest) -> str:
    encoded = json.dumps(
        request.content.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


class FakeLLM(LLMClient):
    def __init__(
        self,
        recorder: RunRecorder,
        scripts: dict[tuple[str, str], Sequence[LLMResponse | Exception]],
        fallback: Callable[[LLMRequest], LLMResponse] | None = None,
    ) -> None:
        super().__init__(recorder)
        self.scripts = {key: deque(responses) for key, responses in scripts.items()}
        self.calls: list[LLMRequest] = []
        self.fallback = fallback

    async def _generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        script = self.scripts.get((request.agent, input_hash(request)))
        if not script and self.fallback is not None:
            return self.fallback(request)
        if not script:
            raise AssertionError("No scripted FakeLLM response for agent and input hash")
        response = script.popleft()
        if isinstance(response, Exception):
            raise response
        return response
