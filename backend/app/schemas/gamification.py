from datetime import datetime

from pydantic import BaseModel


class XpRecordOut(BaseModel):
    amount: int
    source: str
    created_at: datetime


class GamificationProfile(BaseModel):
    level: int
    level_name: str
    xp: int
    xp_to_next: int
    level_progress: int
    streak: int
    longest_streak: int
    weekly_xp: int
    active_days: list[str]
    today_minutes: int
    daily_goal_minutes: int


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    username: str
    avatar: str | None = None
    xp: int
    is_me: bool = False


class AchievementOut(BaseModel):
    code: str
    name: str
    description: str
    icon: str
    unlocked: bool
    unlocked_at: datetime | None = None
    # 未解锁时用于展示进度；已解锁时为 target
    progress: int = 0
    target: int = 0


class AchievementAck(BaseModel):
    """前端弹完解锁提示后回传的成就 code 列表。"""

    codes: list[str] = []


class DailyQuestOut(BaseModel):
    key: str
    label: str
    target: int
    progress: int
    xp: int
    completed: bool


class ThemeOut(BaseModel):
    """可切换的皮肤。皮肤免费，没有价格与拥有状态。"""

    code: str
    name: str
    colors: list[str]
