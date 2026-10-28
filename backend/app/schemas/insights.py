from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Period(StrEnum):
    WEEK = "7d"
    MONTH = "30d"
    QUARTER = "90d"
    THIS_WEEK = "this_week"
    THIS_MONTH = "this_month"


class AnalyticsTool(StrEnum):
    AWAITING = "leads_awaiting_reply"
    NOT_FOLLOWED = "leads_not_followed_up"
    SILENT = "customers_who_went_silent"
    TOP = "top_enquired_items"
    TREND = "enquiry_trend"
    INTENT = "intent_breakdown"
    FUNNEL = "quote_funnel"
    QUOTES = "quotes_by_status"
    RESPONSE = "avg_first_response_time"
    GAPS = "knowledge_gaps"
    CHANNEL = "channel_breakdown"
    LOST = "lost_reasons"


class InsightQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class InsightPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: AnalyticsTool | None
    period: Period = Period.MONTH
    days: int = Field(default=2, ge=1, le=365)
    limit: int = Field(default=10, ge=1, le=50)
    granularity: Literal["day", "week"] = "day"
    status: Literal[
        "draft", "pending_approval", "sent", "viewed", "accepted", "rejected", "expired"
    ] = "accepted"
    open_only: bool = True


Cell = str | int | None


class AnalyticsResult(BaseModel):
    columns: list[str]
    rows: list[dict[str, Cell]]
    total: int
    truncated: bool = False


class ChartSpec(BaseModel):
    kind: Literal["bar", "line"]
    title: str
    x_key: str
    y_key: str
    rows: list[dict[str, Cell]]


class InsightAnswer(BaseModel):
    text: str
    table: list[dict[str, Cell]] | None = None
    columns: list[str] = Field(default_factory=list)
    chart_spec: ChartSpec | None = None
    suggested_actions: list[str] = Field(default_factory=list)
    tool: AnalyticsTool | None = None
    period_start: datetime
    period_end: datetime
    total: int = 0
    truncated: bool = False


class Overview(BaseModel):
    period_start: datetime
    period_end: datetime
    enquiries: int
    inbound_messages: int
    closed_conversations: int
    ai_resolved_conversations: int
    ai_resolution_rate_pct: int | None
    first_response: AnalyticsResult
    trend: AnalyticsResult
    top_items: AnalyticsResult
    intent_mix: AnalyticsResult
    funnel: AnalyticsResult
    channels: AnalyticsResult
    open_gaps: int


class DigestView(BaseModel):
    id: UUID
    week_start: datetime
    period_end: datetime
    answer: InsightAnswer
