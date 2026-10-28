from typing import cast

from fastapi import APIRouter, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analytics.service import InsightsService
from app.core.deps import Config, Context, Session
from app.llm.factory import make_llm
from app.repositories.agent_runs import DatabaseRunRecorder
from app.schemas.insights import DigestView, InsightAnswer, InsightQuestion, Overview, Period

router = APIRouter()


@router.get("/analytics/overview", response_model=Overview)
async def overview(session: Session, ctx: Context, period: Period = Period.MONTH) -> Overview:
    return await InsightsService(session, ctx).overview(period)


@router.post("/insights/ask", response_model=InsightAnswer)
async def ask(
    body: InsightQuestion, session: Session, ctx: Context, config: Config, request: Request
) -> InsightAnswer:
    sessions = cast(async_sessionmaker[AsyncSession], request.app.state.sessions)
    llm = make_llm(config, DatabaseRunRecorder(sessions))
    return await InsightsService(session, ctx).ask(body, llm)


@router.get("/insights/digest/latest", response_model=DigestView | None)
async def digest(session: Session, ctx: Context) -> DigestView | None:
    return await InsightsService(session, ctx).latest_digest()
