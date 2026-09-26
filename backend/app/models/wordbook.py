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

    __tablename__ = "daily_tasks"
    __table_args__ = (UniqueConstraint("user_id", "task_date", name="uq_daily_task_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_date: Mapped[str] = mapped_column(String(10), index=True)

    target_words: Mapped[int] = mapped_column(Integer, default=30)
    target_scenarios: Mapped[int] = mapped_column(Integer, default=1)
    target_articles: Mapped[int] = mapped_column(Integer, default=1)
    target_minutes: Mapped[int] = mapped_column(Integer, default=15)

    done_words: Mapped[int] = mapped_column(Integer, default=0)
    done_scenarios: Mapped[int] = mapped_column(Integer, default=0)
    done_articles: Mapped[int] = mapped_column(Integer, default=0)
    done_minutes: Mapped[int] = mapped_column(Integer, default=0)

    xp_earned: Mapped[int] = mapped_column(Integer, default=0)
    bonus_xp: Mapped[int] = mapped_column(Integer, default=0)
    words_xp_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    scenarios_xp_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    articles_xp_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContributionRecord(Base):

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

    __tablename__ = "word_study_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    vocabulary_id: Mapped[int] = mapped_column(
        ForeignKey("vocabulary.id", ondelete="CASCADE"), index=True
    )
    book_code: Mapped[str] = mapped_column(String(32), default="", index=True)
    mode: Mapped[str] = mapped_column(String(8), default="new")
    action: Mapped[str] = mapped_column(String(12), default="remember")
    study_date: Mapped[str] = mapped_column(String(10), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WordQuizSession(Base):

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

    __tablename__ = "word_audio"
    __table_args__ = (UniqueConstraint("word", "accent", name="uq_word_audio_word_accent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(64), index=True)
    accent: Mapped[str] = mapped_column(String(8), default="us")
    filename: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(32), default="tts")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
