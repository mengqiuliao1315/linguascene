"""词书 / 每日任务 / 贡献值 / 单词音频 相关模型。

与既有 Vocabulary / UserVocabulary 配合：
- Vocabulary 保存单词本体（含音标、例句、所属词书）
- UserVocabulary 保存"我的词库"学习状态（含收藏）
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Wordbook(Base):
    """词书元数据：四级 / 六级 / 新概念三 / 雅思 ..."""

    __tablename__ = "wordbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    name_zh: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(16), default="📘")
    level: Mapped[str] = mapped_column(String(8), default="B1")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class DailyTask(Base):
    """每个用户每天一条学习计划，记录目标与完成度。"""

    __tablename__ = "daily_tasks"
    __table_args__ = (UniqueConstraint("user_id", "task_date", name="uq_daily_task_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    target_words: Mapped[int] = mapped_column(Integer, default=20)
    target_scenarios: Mapped[int] = mapped_column(Integer, default=1)
    target_articles: Mapped[int] = mapped_column(Integer, default=1)
    target_minutes: Mapped[int] = mapped_column(Integer, default=15)

    # 背单词的每日目标按「新学 / 复习」分开计，两者共用上面的 done_words 总进度。
    target_new_words: Mapped[int] = mapped_column(Integer, default=15)
    target_review_words: Mapped[int] = mapped_column(Integer, default=30)

    done_words: Mapped[int] = mapped_column(Integer, default=0)
    done_new_words: Mapped[int] = mapped_column(Integer, default=0)
    done_review_words: Mapped[int] = mapped_column(Integer, default=0)
    done_scenarios: Mapped[int] = mapped_column(Integer, default=0)
    done_articles: Mapped[int] = mapped_column(Integer, default=0)
    done_minutes: Mapped[int] = mapped_column(Integer, default=0)

    xp_earned: Mapped[int] = mapped_column(Integer, default=0)
    bonus_xp: Mapped[int] = mapped_column(Integer, default=0)
    # 三个子项各自的 10 XP 只发一次，重复调用结算接口时靠这三个开关去重。
    words_xp_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    scenarios_xp_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    articles_xp_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContributionRecord(Base):
    """贡献值流水：发布学习内容（文章、场景、论坛帖）获得。"""

    __tablename__ = "contribution_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(48), default="publish_content")
    ref_type: Mapped[str] = mapped_column(String(32), default="")
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WordStudyLog(Base):
    """一次背单词作答的流水。

    每日的「新学 / 复习」进度按这张表实时统计，而不是在 DailyTask 上累加计数器：
    只有真正学过的新词才算新学，且两个模式不会互相污染。
    """

    __tablename__ = "word_study_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    vocabulary_id: Mapped[int] = mapped_column(
        ForeignKey("vocabulary.id", ondelete="CASCADE"), index=True
    )
    book_code: Mapped[str] = mapped_column(String(32), default="", index=True)
    mode: Mapped[str] = mapped_column(String(8), default="new")  # new | review
    action: Mapped[str] = mapped_column(String(12), default="remember")  # forget|remember|mastered
    study_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WordQuizSession(Base):
    """一轮随机测验的进度。

    每个用户同时只保留一条记录：重新抽题会覆盖旧的，退出测验则原样留着，
    下次可以接着答没答完的词。queue_json 存还没答对的单词 id 列表，
    答对出队、答错挪到队尾，队列空即测验完成。
    """

    __tablename__ = "word_quiz_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    queue_json: Mapped[str] = mapped_column(Text, default="[]")
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WordAudio(Base):
    """单词发音音频缓存（本地 storage/audio 下的文件）。"""

    __tablename__ = "word_audio"
    __table_args__ = (UniqueConstraint("word", "accent", name="uq_word_audio_word_accent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(64), index=True)
    accent: Mapped[str] = mapped_column(String(8), default="us")
    filename: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(32), default="tts")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
