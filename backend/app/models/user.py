from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    password_enc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role: Mapped[str] = mapped_column(String(16), default="USER")
    cefr_level: Mapped[str] = mapped_column(String(4), default="B1")
    interests: Mapped[str] = mapped_column(String(255), default="")

    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    coins: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[str | None] = mapped_column(String(10), nullable=True)

    theme: Mapped[str] = mapped_column(String(32), default="ocean")
    owned_themes: Mapped[str] = mapped_column(String(255), default="ocean")

    ai_active_config_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_active_share_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    quests_seeded: Mapped[bool] = mapped_column(Integer, default=0)

    pet_species: Mapped[str] = mapped_column(String(32), default="hedgehog")
    pet_name: Mapped[str] = mapped_column(String(32), default="")
    last_login_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    login_streak: Mapped[int] = mapped_column(Integer, default=0)
    best_login_streak: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversations = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    xp_records = relationship(
        "XpRecord",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def interest_list(self) -> list[str]:
        return [i for i in self.interests.split(",") if i]
