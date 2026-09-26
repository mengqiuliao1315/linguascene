from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.scenarios import scenario_payload
from app.core.database import get_db
from app.models.content import Article
from app.models.learning import Conversation, Scenario
from app.models.user import User
from app.schemas.content import ArticleCardOut
from app.schemas.dashboard import DashboardOut
from app.schemas.gamification import DailyQuestOut
from app.schemas.learning import ScenarioOut
from app.services import gamification_service, levels, vocabulary_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


_LOCAL_TZ = timezone(timedelta(hours=8))


def _greeting() -> str:
    hour = datetime.now(_LOCAL_TZ).hour
    if hour < 5:
        return "Good night"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


@router.get("", response_model=DashboardOut)
def dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DashboardOut:
    level, level_name = levels.level_for_xp(user.xp)

    recent_ids = [
        r
        for r in db.execute(
            select(Conversation.scenario_id)
            .where(Conversation.user_id == user.id, Conversation.scenario_id.isnot(None))
            .order_by(Conversation.started_at.desc())
            .limit(5)
        ).scalars().all()
        if r
    ]
    completed_ids = set(
        db.execute(
            select(Conversation.scenario_id).where(
                Conversation.user_id == user.id,
                Conversation.is_completed.is_(True),
                Conversation.scenario_id.isnot(None),
            )
        ).scalars().all()
    )

    all_scenarios = db.execute(
        select(Scenario).where(Scenario.is_published.is_(True)).order_by(Scenario.id)
    ).scalars().all()

    recent_categories = {s.category for s in all_scenarios if s.id in recent_ids}
    today_mission = next(
        (
            s
            for s in all_scenarios
            if s.id not in completed_ids and s.category in recent_categories
        ),
        None,
    ) or next((s for s in all_scenarios if s.id not in completed_ids), None)

    mission_id = today_mission.id if today_mission else None
    recommended = [s for s in all_scenarios if s.id != mission_id][:4]

    article = db.execute(
        select(Article).order_by(Article.published_at.desc()).limit(1)
    ).scalar_one_or_none()

    return DashboardOut(
        greeting=_greeting(),
        username=user.username,
        streak=user.streak,
        xp=user.xp,
        level=level,
        level_name=level_name,
        level_progress=levels.level_progress(user.xp),
        xp_to_next=levels.xp_to_next(user.xp),
        today_mission=(
            ScenarioOut.model_validate(scenario_payload(today_mission))
            if today_mission
            else None
        ),
        recommended_scenarios=[
            ScenarioOut.model_validate(scenario_payload(s)) for s in recommended
        ],
        recommended_article=(
            ArticleCardOut.model_validate(article) if article else None
        ),
        daily_quests=[
            DailyQuestOut.model_validate(q)
            for q in gamification_service.daily_quests(db, user)
        ],
        review_due_count=vocabulary_service.due_count(db, user),
    )
