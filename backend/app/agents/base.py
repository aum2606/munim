from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ClassVar, Literal
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel

from app.core.tenant import TenantContext
from app.llm import LLMClient
from app.llm.types import LLMRequest, ToolCall


class BaseAgent[I: BaseModel, O: BaseModel]:
    name: ClassVar[str]
    allowed_tools: ClassVar[tuple[str, ...]] = ()
    model_slot: ClassVar[Literal["router", "reasoning", "cheap"]] = "reasoning"

    def __init__(self, llm: LLMClient, output_type: type[O]) -> None:
        self.llm, self.output_type = llm, output_type

    async def call_tool[T](self, name: str, operation: Callable[[], Awaitable[T]]) -> T:
        if name not in self.allowed_tools:
            raise PermissionError("Tool is outside the agent allow-list")
        return await operation()

    async def run(
        self,
        ctx: TenantContext,
        body: I,
        *,
        message_id: UUID | None = None,
        tools_used: list[ToolCall] | None = None,
    ) -> O:
        env = Environment(
            loader=FileSystemLoader(Path(__file__).parent / "prompts"),
            undefined=StrictUndefined,
            autoescape=False,
        )
        request = LLMRequest(
            agent=self.name,
            model_slot=self.model_slot,
            system=env.get_template(self.name + ".jinja").render(),
            content=body,
            output_schema=self.output_type.model_json_schema(),
            allowed_tools=self.allowed_tools,
            tools_used=tools_used or [],
        )
        return await self.llm.structured(ctx, request, self.output_type, message_id)
