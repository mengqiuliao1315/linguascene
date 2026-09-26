"""AI 模型配置。

一个用户可以添加多个供应商，每个供应商各含多个模型：
- AiProviderConfig：用户自己接入的一份供应商配置（Base URL + Key + 模型列表），
  一人可有多条，`active_model` 指定这条配置当前用哪个模型。
- AiShare：用户把自己的一条供应商配置分享出来给其他人用，可随时停用/删除。
- AiShareAdoption：谁采纳了哪条分享，用于回显"来自 xxx 的分享"。
- AiShareDismissal：谁关掉了哪条分享的登录弹窗，关掉后不再推送。

全站唯一的模型来源就是"某个用户配置/分享的模型"，没有平台内置的免费模型。
Key 一律加密存储，见 app.core.crypto。
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AiProviderConfig(Base):
    """用户自接入的一份供应商配置。一个用户可以有多条。"""

    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 供应商展示名，例如"我的 DeepSeek"
    name: Mapped[str] = mapped_column(String(64), default="")
    base_url: Mapped[str] = mapped_column(String(255), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    # 接入格式：openai / openai_responses / anthropic / gemini，见 app.ai.provider
    api_format: Mapped[str] = mapped_column(String(32), default="openai")
    # 这条供应商下可选的模型名，JSON 数组字符串。保留成文本是为了老库补列简单。
    models: Mapped[str] = mapped_column(Text, default="[]")
    # 当前选用的模型名，须在 models 里
    active_model: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AiShare(Base):
    """用户分享出来的一份供应商配置。

    分享时把配置复制一份存在这里（含加密 Key），因此分享与"我的供应商"
    彼此独立：删掉自己的配置不影响已分享的，反之亦然。
    is_active=False（或删除本行）后立即从别人的可选列表与弹窗里消失。
    """

    __tablename__ = "ai_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 分享展示名，例如"某某的 DeepSeek"
    title: Mapped[str] = mapped_column(String(64), default="")
    base_url: Mapped[str] = mapped_column(String(255), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    api_format: Mapped[str] = mapped_column(String(32), default="openai")
    # 分享者可用的模型名，JSON 数组字符串
    models: Mapped[str] = mapped_column(Text, default="[]")
    # 分享者指定的默认模型，采纳者用它
    active_model: Mapped[str] = mapped_column(String(128), default="")
    # 给使用者的备注/说明
    note: Mapped[str] = mapped_column(String(200), default="")
    # 关掉开关即停止推送给其他人，但保留记录
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AiShareAdoption(Base):
    """谁采纳了哪条分享：一人一条，换采纳会覆盖。"""

    __tablename__ = "ai_share_adoptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_ai_share_adoption_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    share_id: Mapped[int] = mapped_column(
        ForeignKey("ai_shares.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiShareDismissal(Base):
    """谁关掉了哪条分享的登录弹窗。关掉后不再对这个人弹同一条分享。"""

    __tablename__ = "ai_share_dismissals"
    __table_args__ = (
        UniqueConstraint("user_id", "share_id", name="uq_ai_share_dismissal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    share_id: Mapped[int] = mapped_column(
        ForeignKey("ai_shares.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
