from pydantic import BaseModel

from app.schemas.content import ArticleCardOut
from app.schemas.gamification import DailyQuestOut
from app.schemas.learning import ScenarioOut


class DashboardOut(BaseModel):
    greeting: str
    username: str
    streak: int
    xp: int
    level: int
    level_name: str
    level_progress: int
    xp_to_next: int
    today_mission: ScenarioOut | None = None
    recommended_scenarios: list[ScenarioOut] = []
    recommended_article: ArticleCardOut | None = None
    daily_quests: list[DailyQuestOut] = []
    review_due_count: int = 0
