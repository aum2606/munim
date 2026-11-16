import uuid
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from pydantic import BaseModel

from app.core.context import TenantContext
from app.core.errors import ForbiddenError
from app.db.session import SessionMaker
from app.llm.base import LLMClient, Slot
from app.llm.prompting import render_prompt
from app.llm.recording import agent_run


class ToolBox:
    """The tools an agent may call. Anything outside its allow-list is refused, so a prompt
    injection that talks an agent into "using" another tool still cannot reach it."""

    def __init__(
        self, allowed: frozenset[str], tools: dict[str, Callable[..., Awaitable[Any]]]
    ) -> None:
        self._allowed = allowed
        self._tools = tools
        self.calls: list[dict[str, Any]] = []  # recorded into agent_runs.tool_calls

    async def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self._allowed:
            raise ForbiddenError(f"This agent may not use the tool {name!r}")
        result = await self._tools[name](**kwargs)
        self.calls.append({"tool": name, "args": sorted(kwargs), "results": _count(result)})
        return result


def _count(result: Any) -> int | None:
    return len(result) if isinstance(result, list) else None


class BaseAgent:
    """An agent is a prompt template, a model slot, typed I/O and a tool allow-list."""

    name: ClassVar[str]
    template: ClassVar[str]
    slot: ClassVar[Slot]
    tools: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, llm: LLMClient, sessionmaker: SessionMaker) -> None:
        self._llm = llm
        self._sessionmaker = sessionmaker

    async def invoke[O: BaseModel](
        self,
        ctx: TenantContext,
        output_model: type[O],
        record: BaseModel,
        *,
        message_id: uuid.UUID | None = None,
        toolbox: ToolBox | None = None,
        template: str | None = None,
        **prompt_variables: Any,
    ) -> O:
        """Render the prompt, call the model for validated output, and log an agent_runs row."""
        messages, version = render_prompt(template or self.template, **prompt_variables)
        async with agent_run(
            self._sessionmaker,
            ctx,
            agent=self.name,
            prompt_version=version,
            input=record.model_dump(mode="json"),
        ) as run:
            run.message_id = message_id
            if toolbox is not None:
                run.tool_calls = toolbox.calls  # same list: later calls are recorded too
            output, run.result = await self._llm.structured(self.slot, messages, output_model)
            run.output = output.model_dump(mode="json")
        return output
