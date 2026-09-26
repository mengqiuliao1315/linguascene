from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.learning import Scenario
from app.models.user import User
from app.schemas.learning import ConversationOut, ScenarioOut
from app.services import audio_service

from app.services.scenarios import scenario_payload

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


@router.get("", response_model=list[ScenarioOut])
def list_scenarios(
    category: str | None = Query(default=None),
    level: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[ScenarioOut]:
    query = select(Scenario).where(Scenario.is_published.is_(True)).order_by(Scenario.id)
    if category:
        query = query.where(Scenario.category == category)
    if level:
        query = query.where(Scenario.level == level)
    rows = db.execute(query).scalars().all()
    return [ScenarioOut.model_validate(scenario_payload(s)) for s in rows]


@router.get("/{scenario_id}", response_model=ScenarioOut)
def get_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ScenarioOut:
    scenario = db.execute(
        select(Scenario).where(
            Scenario.id == scenario_id, Scenario.is_published.is_(True)
        )
    ).scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="场景不存在")

    audio_service.prewarm_text(scenario.opening_line)
    return ScenarioOut.model_validate(scenario_payload(scenario))
