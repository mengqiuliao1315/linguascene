from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Article(Base):

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(128), default="")
    url: Mapped[str] = mapped_column(String(512), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(4), default="B1")
    category: Mapped[str] = mapped_column(String(32), default="Technology", index=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    read_minutes: Mapped[int] = mapped_column(Integer, default=5)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_builtin: Mapped[bool] = mapped_column(Integer, default=1)

    analysis = relationship(
        "ArticleAnalysis", back_populates="article", uselist=False, cascade="all, delete-orphan"
    )


class ArticleAnalysis(Base):
    __tablename__ = "article_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), unique=True
    )
    summary: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(4), default="B1")
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    phrases_json: Mapped[str] = mapped_column(Text, default="[]")
    grammar_json: Mapped[str] = mapped_column(Text, default="[]")
    questions_json: Mapped[str] = mapped_column(Text, default="[]")
    speaking_json: Mapped[str] = mapped_column(Text, default="[]")
    writing_task: Mapped[str] = mapped_column(Text, default="")
    sentences_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article = relationship("Article", back_populates="analysis")


class UserContent(Base):

    __tablename__ = "user_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(32), default="text")
    status: Mapped[str] = mapped_column(String(16), default="ready")
    analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentences_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Integer, default=0, index=True)
    author_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReadingNote(Base):

    __tablename__ = "reading_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=True, index=True
    )
    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_content.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    sentence_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="word")
    text: Mapped[str] = mapped_column(String(512), default="")
    start_offset: Mapped[int] = mapped_column(Integer, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, default=0)
    lemma: Mapped[str] = mapped_column(String(128), default="")
    meaning: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="blue")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
