from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.learning import Scenario
from app.models.user import User
from app.schemas.learning import ConversationOut, ScenarioOut
from app.services import audio_service

# 序列化逻辑收敛到 services；这里保留同名导入，兼容 dashboard / conversations 的引用
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
        select(Scenario).where(Scenario.id == scenario_id)
    ).scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="场景不存在")

    # 用户点开场景详情，接着多半就是「开始对话」并听到这句开场白。趁他读说明的
    # 时候先把音频合成好（后台线程，这里不等），进对话页时就是即时出声。
    audio_service.prewarm_text(scenario.opening_line)
    return ScenarioOut.model_validate(scenario_payload(scenario))
