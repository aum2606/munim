from pydantic import BaseModel


class UsageRowOut(BaseModel):
    agent: str
    model: str | None
    calls: int
    errors: int
    prompt_tokens: int
    completion_tokens: int
    cost_micros: int  # micro-dollars at list price
    p50_ms: int
    p95_ms: int


class OverviewOut(BaseModel):
    days: int
    customer_messages: int
    ai_replies: int
    staff_replies: int
    conversations_needing_a_person: int
    open_knowledge_gaps: int
    leads_by_stage: dict[str, int]
    quotes_by_status: dict[str, int]
    accepted_value_paise: int
    model_calls_24h: int
    model_call_budget: int  # 0 means no limit
    turns: int
    cost_micros: int
    cost_per_turn_micros: int
    unpriced_calls: int
    first_response_p50_ms: int | None
    first_response_p95_ms: int | None
    usage: list[UsageRowOut]
