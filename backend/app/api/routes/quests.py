from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.social import (
    HeatmapOut,
    LeaderboardOut,
    QuestCheckUpdate,
    QuestCreate,
    QuestMetricOut,
    QuestOut,
    QuestUpdate,
    UserStats,
)
from app.services import levels, social_service

router = APIRouter(prefix="/api", tags=["quests"])


@router.get("/quests", response_model=list[QuestOut])
def list_quests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[QuestOut]:
    """用户的每日计划，带当天进度与打勾状态。

    新用户第一次调用时，会用 levels.DAILY_QUESTS 播一次默认计划，
    之后列表完全由用户自己增删改。播种只在这次 GET 里发生，所以要提交。
    """
    quests = social_service.merged_quests(db, user)
    db.commit()
    return [QuestOut.model_validate(q) for q in quests]


@router.get("/quests/metrics", response_model=list[QuestMetricOut])
def list_metrics(user: User = Depends(get_current_user)) -> list[QuestMetricOut]:
    """计划可选的统计口径，只影响进度显示。"""
    return [QuestMetricOut.model_validate(m) for m in levels.QUEST_METRICS]


@router.post("/quests", response_model=QuestOut, status_code=status.HTTP_201_CREATED)
def create_quest(
    payload: QuestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuestOut:
    quest = social_service.create_quest(db, user, payload)
    db.commit()
    return QuestOut.model_validate(social_service.quest_payload(db, user, quest))


@router.patch("/quests/{quest_id}", response_model=QuestOut)
def update_quest(
    quest_id: int,
    payload: QuestUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuestOut:
    quest = social_service.get_quest(db, user, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="计划不存在")

    social_service.update_quest(db, quest, payload)
    db.commit()
    return QuestOut.model_validate(social_service.quest_payload(db, user, quest))


@router.post("/quests/{quest_id}/check", response_model=QuestOut)
def check_quest(
    quest_id: int,
    payload: QuestCheckUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuestOut:
    """用户自己打勾 / 取消打勾。打勾同时算当天一次学习活动。"""
    quest = social_service.get_quest(db, user, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="计划不存在")

    result = social_service.set_quest_checked(db, user, quest, payload.completed)
    db.commit()
    return QuestOut.model_validate(result)


@router.delete("/quests/{quest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quest(
    quest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    quest = social_service.get_quest(db, user, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="计划不存在")
    social_service.delete_quest(db, quest)
    db.commit()


@router.get("/stats/heatmap", response_model=HeatmapOut)
def heatmap(
    days: int = social_service.HEATMAP_DAYS,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HeatmapOut:
    """打卡热力图：每天的学习活动次数。"""
    days = max(30, min(days, 400))
    return HeatmapOut.model_validate(social_service.heatmap(db, user, days))


@router.get("/stats/heatmap/{user_id}", response_model=HeatmapOut)
def user_heatmap(
    user_id: int,
    days: int = social_service.HEATMAP_DAYS,
    db: Session = Depends(get_db),
    _me: User = Depends(get_current_user),
) -> HeatmapOut:
    """看别人的打卡图。"""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    days = max(30, min(days, 400))
    return HeatmapOut.model_validate(social_service.heatmap(db, target, days))


@router.get("/stats/leaderboard", response_model=LeaderboardOut)
def leaderboard(
    metric: str = "xp",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LeaderboardOut:
    """全站排行。柱状图与列表来自同一份数据。

    metric: xp（累计经验）| streak（连续打卡天数）| contribution（贡献值）
    """
    if metric not in ("xp", "streak", "contribution"):
        raise HTTPException(status_code=400, detail="metric 只支持 xp、streak 或 contribution")
    return LeaderboardOut.model_validate(social_service.leaderboard(db, user, metric))


@router.get("/stats/users/{user_id}", response_model=UserStats)
def user_stats(
    user_id: int,
    db: Session = Depends(get_db),
    _me: User = Depends(get_current_user),
) -> UserStats:
    """某个用户的公开数据，个人主页用。"""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserStats.model_validate(social_service.public_stats(db, target))
