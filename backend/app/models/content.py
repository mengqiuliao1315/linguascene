from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Article(Base):
    """平台自带的阅读材料。"""

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
    # 逐句讲解缓存：平台文章与用户上传共用同一套精读流程
    sentences_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article = relationship("Article", back_populates="analysis")


class UserContent(Base):
    """用户上传的文章，可公布给其他人阅读。"""

    __tablename__ = "user_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(32), default="text")
    status: Mapped[str] = mapped_column(String(16), default="ready")  # ready | failed
    analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 逐句讲解缓存，按句索引存，避免每次打开都重新调用模型
    sentences_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 公布后其他用户可阅读、划词，并在其上写自己的笔记
    is_public: Mapped[bool] = mapped_column(Integer, default=0, index=True)
    author_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReadingNote(Base):
    """精读批注。

    归属 (文档, 用户)：同一篇公开文章下，每个读者写自己的一份笔记。
    文档可能是平台文章（article_id）或用户上传（content_id），二者必有其一。
    """

    __tablename__ = "reading_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=True, index=True
    )
    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_content.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # 句子在文章中的序号，用于把批注对齐到原文
    sentence_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # word | phrase | sentence | note
    kind: Mapped[str] = mapped_column(String(16), default="word")
    text: Mapped[str] = mapped_column(String(512), default="")
    # 选中文字在该句内的字符区间 [start_offset, end_offset)，用于精确染色。
    # 老笔记这两列都是 0，前端回退到按文本匹配。
    start_offset: Mapped[int] = mapped_column(Integer, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, default=0)
    # 单词的原型（lemma）。划词得到的词形入词库前要还原成原型，
    # 否则 studies 和 study 会变成两条记录。
    lemma: Mapped[str] = mapped_column(String(128), default="")
    meaning: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # 高亮颜色，前端按这个值渲染标记
    color: Mapped[str] = mapped_column(String(16), default="blue")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
