import json
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.core.tenant import TenantContext
from app.llm.types import LLMRequest, LLMResponse

T = TypeVar("T", bound=BaseModel)


class RunRecorder(Protocol):
    async def record(
        self,
        ctx: TenantContext,
        *,
        agent: str,
        model: str,
        request: dict[str, Any],
        output: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        latency_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd_micros: int,
        status: str,
        error: str | None,
        message_id: UUID | None,
    ) -> None: ...


def recorded_call(
    method: Callable[..., Awaitable[LLMResponse]],
) -> Callable[..., Awaitable[LLMResponse]]:
    @wraps(method)
    async def wrapped(
        self: "LLMClient",
        ctx: TenantContext,
        request: LLMRequest,
        message_id: UUID | None = None,
        output_type: type[BaseModel] | None = None,
    ) -> LLMResponse:
        started = time.perf_counter_ns()
        response: LLMResponse | None = None
        status, error_name = "error", None
        try:
            response = await method(self, ctx, request, message_id)
            if any(call.name not in request.allowed_tools for call in response.tool_calls):
                raise PermissionError("Tool is not allowed for this agent")
            if output_type is not None:
                output_type.model_validate(response.output)
            status = "success"
            return response
        except Exception as error:
            status = (
                "invalid" if isinstance(error, (ValidationError, json.JSONDecodeError)) else "error"
            )
            error_name = type(error).__name__
            raise
        finally:
            await self.recorder.record(
                ctx,
                agent=request.agent,
                model=response.model if response else request.model_slot,
                request=request.model_dump(mode="json"),
                output=response.output if response else {},
                tool_calls=[c.model_dump() for c in response.tool_calls] if response else [],
                latency_ms=(time.perf_counter_ns() - started) // 1_000_000,
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                cost_usd_micros=response.cost_usd_micros if response else 0,
                status=status,
                error=error_name,
                message_id=message_id,
            )

    return wrapped


class LLMClient(ABC):
    def __init__(self, recorder: RunRecorder) -> None:
        self.recorder = recorder

    @abstractmethod
    async def _generate(self, request: LLMRequest) -> LLMResponse: ...

    @recorded_call
    async def generate(
        self,
        ctx: TenantContext,
        request: LLMRequest,
        message_id: UUID | None = None,
        output_type: type[BaseModel] | None = None,
    ) -> LLMResponse:
        return await self._generate(request)

    async def structured(
        self,
        ctx: TenantContext,
        request: LLMRequest,
        output_type: type[T],
        message_id: UUID | None = None,
    ) -> T:
        validated_request = request.model_copy(
            update={"output_schema": output_type.model_json_schema()}
        )
        for attempt in range(2):
            try:
                response = await self.generate(
                    ctx, validated_request, message_id, output_type=output_type
                )
                return output_type.model_validate(response.output)
            except (ValidationError, json.JSONDecodeError):
                if attempt:
                    raise
                validated_request = validated_request.model_copy(
                    update={
                        "system": request.system
                        + " Return an object matching the supplied JSON schema."
                    }
                )
        raise AssertionError("unreachable")
