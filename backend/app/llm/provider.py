import json

import httpx

from app.core.config import Settings
from app.llm.client import LLMClient, RunRecorder
from app.llm.types import LLMRequest, LLMResponse


class OpenAICompatibleLLM(LLMClient):
    """https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat"""

    def __init__(
        self,
        recorder: RunRecorder,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(recorder)
        self.settings, self.transport = settings, transport

    async def _generate(self, request: LLMRequest) -> LLMResponse:
        model = getattr(self.settings, f"llm_model_{request.model_slot}")
        if not model or not self.settings.llm_api_key.get_secret_value():
            raise ValueError("LLM model and credentials must be configured")
        async with httpx.AsyncClient(
            transport=self.transport, timeout=self.settings.llm_timeout_s
        ) as client:
            response = await client.post(
                self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key.get_secret_value()}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": request.system},
                        {
                            "role": "user",
                            "content": "<customer_data>"
                            + request.content.model_dump_json()
                            + "</customer_data>",
                        },
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": request.agent,
                            "strict": True,
                            "schema": request.output_schema,
                        },
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
            message = payload["choices"][0]["message"]
            if message.get("refusal"):
                raise ValueError("Provider refused structured output")
            if message.get("tool_calls"):
                raise PermissionError("Provider tool execution is not enabled")
            usage = payload.get("usage", {})
            return LLMResponse(
                output=json.loads(message["content"]),
                model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )
