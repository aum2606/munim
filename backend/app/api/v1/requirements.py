from fastapi import APIRouter

from app.core.deps import Context, Owner, Session
from app.repositories.requirements import RequirementRepository
from app.schemas.requirements import RequirementDefinition, RequirementView

router = APIRouter()


@router.get("/requirement-schemas", response_model=list[RequirementView])
async def schemas(session: Session, ctx: Context) -> list[RequirementView]:
    repository = RequirementRepository(session, ctx)
    await repository.ensure_defaults()
    result = [RequirementView.model_validate(schema) for schema in await repository.list()]
    await session.commit()
    return result


@router.put("/requirement-schemas", response_model=RequirementView)
async def update_schema(
    body: RequirementDefinition, session: Session, ctx: Owner
) -> RequirementView:
    result = await RequirementRepository(session, ctx).save(body)
    await session.commit()
    return RequirementView.model_validate(result)
