"""社交与个人计划相关 Schema。"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# 用户输入的文字统一先去掉首尾空白再校验长度，否则 "   " 能通过 min_length=1。
# 服务层还会再 strip 一次，这里是为了让空白输入直接返回 422 而不是存进库里。
NonBlank = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
]


# ------------------------------------------------------------------ 每日计划


class QuestMetricOut(BaseModel):
    key: str
    label: str
    unit: str


class QuestOut(BaseModel):
    """系统任务与自建计划共用同一形状，custom 区分来源。"""

    id: int | None = None
    key: str
    label: str
    icon: str = "🎯"
    target: int
    progress: int = 0
    xp: int
    completed: bool = False
    custom: bool = False
    metric: str = ""


class QuestCreate(BaseModel):
    label: NonBlank = Field(max_length=64)
    metric: str = Field(default="words", max_length=32)
    target: int = Field(default=10, ge=1, le=500)
    xp: int = Field(default=10, ge=0, le=200)
    icon: str = Field(default="🎯", max_length=8)


class QuestUpdate(BaseModel):
    label: NonBlank | None = Field(default=None, max_length=64)
    metric: str | None = Field(default=None, max_length=32)
    target: int | None = Field(default=None, ge=1, le=500)
    xp: int | None = Field(default=None, ge=0, le=200)
    icon: str | None = Field(default=None, max_length=8)
    is_active: bool | None = None


class QuestCheckUpdate(BaseModel):
    """用户手动打勾 / 取消打勾。"""

    completed: bool


# ------------------------------------------------------------------ 打卡与统计


class HeatCell(BaseModel):
    date: str
    count: int
    level: int  # 0-4，用于前端选色


class HeatmapOut(BaseModel):
    cells: list[HeatCell]
    total_days: int
    current_streak: int
    longest_streak: int
    total_active_days: int


class UserStats(BaseModel):
    """用户公开数据。贡献值口径见 wordbook_service.CONTRIBUTION_RULES。"""

    user_id: int
    username: str
    avatar: str | None = None
    role: str = "USER"
    cefr_level: str = "B1"
    level: int = 1
    level_name: str = "Beginner"
    xp: int = 0
    streak: int = 0
    longest_streak: int = 0
    created_at: datetime | None = None

    contribution: int = 0
    published_articles: int = 0
    forum_posts: int = 0
    forum_comments: int = 0
    likes_received: int = 0

    words_today: int = 0
    articles_today: int = 0
    words_total: int = 0
    scenarios_done: int = 0
    active_days: int = 0


class ChartBar(BaseModel):
    user_id: int
    username: str
    avatar: str | None = None
    value: int
    is_me: bool = False


class LeaderRow(ChartBar):
    rank: int
    level: int = 1
    level_name: str = "Beginner"
    streak: int = 0


class LeaderboardOut(BaseModel):
    """柱状图和列表来自同一份数据，前端两处渲染同一个响应。"""

    bars: list[ChartBar]
    entries: list[LeaderRow]


# ------------------------------------------------------------------ 好友


class FriendOut(BaseModel):
    user_id: int
    username: str
    avatar: str | None = None
    level: int = 1
    level_name: str = "Beginner"
    xp: int = 0
    streak: int = 0
    online_today: bool = False
    friendship_id: int | None = None


class FriendRequestOut(BaseModel):
    friendship_id: int
    user_id: int
    username: str
    avatar: str | None = None
    created_at: datetime
    incoming: bool = True


class FriendStatusOut(BaseModel):
    state: str  # none | friends | outgoing | incoming | self
    friendship_id: int | None = None


# ------------------------------------------------------------------ 私信


class ChatMessageCreate(BaseModel):
    content: NonBlank = Field(max_length=2000)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sender_id: int
    recipient_id: int
    content: str
    created_at: datetime
    mine: bool = False


class ChatThreadOut(BaseModel):
    user_id: int
    username: str
    avatar: str | None = None
    last_message: str = ""
    last_at: datetime | None = None
    unread: int = 0


# ------------------------------------------------------------------ 论坛


class ForumAuthor(BaseModel):
    user_id: int
    username: str
    avatar: str | None = None
    level: int = 1
    level_name: str = "Beginner"


class PostCreate(BaseModel):
    title: NonBlank = Field(max_length=160)
    content: NonBlank = Field(max_length=20000)
    tags: list[str] = Field(default_factory=list)


class PostUpdate(BaseModel):
    title: NonBlank | None = Field(default=None, max_length=160)
    content: NonBlank | None = Field(default=None, max_length=20000)
    tags: list[str] | None = None


class PostCardOut(BaseModel):
    id: int
    title: str
    summary: str
    truncated: bool = False  # 正文长于摘要上限，卡片需折叠展示
    cover: str | None = None  # 正文首图，列表卡片封面
    tags: list[str]
    author: ForumAuthor
    view_count: int
    like_count: int
    comment_count: int
    liked: bool = False
    is_pinned: bool = False
    is_mine: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class PostDetailOut(PostCardOut):
    content: str


class PostPageOut(BaseModel):
    """分页响应：列表 + 总数，前端据此显示「加载更多」。"""

    items: list[PostCardOut]
    total: int
    offset: int
    limit: int
    has_more: bool


class PopularTag(BaseModel):
    tag: str
    count: int


class CommentCreate(BaseModel):
    content: NonBlank = Field(max_length=2000)


class CommentOut(BaseModel):
    id: int
    content: str
    author: ForumAuthor
    is_mine: bool = False
    created_at: datetime
