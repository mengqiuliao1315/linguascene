from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.gamification import (
    AchievementAck,
    AchievementOut,
    DailyQuestOut,
    GamificationProfile,
    LeaderboardEntry,
    ThemeOut,
)
from app.services import gamification_service, levels

router = APIRouter(prefix="/api/gamification", tags=["gamification"])


@router.get("/profile", response_model=GamificationProfile)
def profile(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GamificationProfile:
    level, level_name = levels.level_for_xp(user.xp)
    return GamificationProfile(
        level=level,
        level_name=level_name,
        xp=user.xp,
        xp_to_next=levels.xp_to_next(user.xp),
        level_progress=levels.level_progress(user.xp),
        streak=user.streak,
        longest_streak=user.longest_streak,
        weekly_xp=gamification_service.weekly_xp(db, user),
        active_days=gamification_service.active_days_this_week(db, user),
        today_minutes=gamification_service.today_minutes(db, user),
        daily_goal_minutes=levels.DAILY_GOAL_MINUTES,
    )


@router.get("/streak")
def streak(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return {
        "streak": user.streak,
        "longest_streak": user.longest_streak,
        "active_days": gamification_service.active_days_this_week(db, user),
        "today_minutes": gamification_service.today_minutes(db, user),
        "daily_goal_minutes": levels.DAILY_GOAL_MINUTES,
    }


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def leaderboard(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LeaderboardEntry]:
    rows = gamification_service.weekly_leaderboard(db, user)
    return [LeaderboardEntry.model_validate(r) for r in rows]


@router.get("/achievements", response_model=list[AchievementOut])
def achievements(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AchievementOut]:
    return [
        AchievementOut.model_validate(a)
        for a in gamification_service.achievements_with_state(db, user)
    ]


@router.get("/achievements/pending", response_model=list[AchievementOut])
def pending_achievements(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AchievementOut]:
    """刚解锁、还没弹过提示的成就。前端在页面切换后轮询这个接口。"""
    return [
        AchievementOut(
            code=a.code,
            name=a.name,
            description=a.description,
            icon=a.icon,
            unlocked=True,
        )
        for a in gamification_service.pending_achievements(db, user)
    ]


@router.post("/achievements/ack")
def ack_achievements(
    payload: AchievementAck,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """前端弹完提示后回填，避免同一成就重复提示。"""
    updated = gamification_service.mark_achievements_notified(db, user, payload.codes)
    db.commit()
    return {"updated": updated}


@router.get("/daily-quests", response_model=list[DailyQuestOut])
def daily_quests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DailyQuestOut]:
    return [
        DailyQuestOut.model_validate(q)
        for q in gamification_service.daily_quests(db, user)
    ]


@router.get("/themes", response_model=list[ThemeOut])
def themes() -> list[ThemeOut]:
    """所有皮肤，全部免费，前端直接切换。"""
    return [ThemeOut.model_validate(i) for i in gamification_service.theme_items()]
