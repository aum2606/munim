from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: str
    model_slot: Literal["router", "reasoning", "cheap"] = "reasoning"
    system: str
    content: BaseModel
    output_schema: dict[str, Any]
    allowed_tools: tuple[str, ...] = ()
    tools_used: list[ToolCall] = Field(default_factory=list)


class LLMResponse(BaseModel):
    output: dict[str, Any]
    model: str = "fake"
    tool_calls: list[ToolCall] = Field(default_factory=list)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cost_usd_micros: int = Field(default=0, ge=0)
