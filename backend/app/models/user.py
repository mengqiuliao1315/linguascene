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
    # 可逆密文仅给管理员在创建/重置时回显一次；列表接口不再解密返回。
    password_enc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 登录令牌版本：改密码时递增，旧 JWT 立即失效。
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role: Mapped[str] = mapped_column(String(16), default="USER")
    cefr_level: Mapped[str] = mapped_column(String(4), default="B1")
    interests: Mapped[str] = mapped_column(String(255), default="")

    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    # 金币已下线：它原本是皮肤的购买货币，但皮肤后来改成全部免费，
    # 于是这枚货币只进不出、没有任何消费场景。**经验值（xp）是唯一的成长货币**。
    # 这列只为兼容老库保留（NOT NULL），不再读写，也不要再接回业务。
    coins: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[str | None] = mapped_column(String(10), nullable=True)

    theme: Mapped[str] = mapped_column(String(32), default="ocean")
    # 皮肤已改为免费自由切换，这列只为兼容老库保留（NOT NULL），不再读写。
    owned_themes: Mapped[str] = mapped_column(String(255), default="ocean")

    # AI 模型选择：用户选中的那条供应商配置 id（自己的或采纳的分享）。
    # 为空表示还没选，按"自己的第一条 → 采纳的分享 → 站点兜底"的顺序回落。
    ai_active_config_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 选中的是分享时，记下分享 id（供应商配置 id 与分享 id 是两套编号）
    ai_active_share_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 每日计划是否已播过默认值。播一次就置 1，用户把默认计划删光也不会
    # 再长出来（见 social_service.ensure_default_quests）。
    quests_seeded: Mapped[bool] = mapped_column(Integer, default=0)

    # 萌宠：只剩刺猬一个形象，默认叫「墩墩」，pet_name 为空表示用户没改过名，
    # 由前端回落到默认称呼。心情与连续陪伴天数来自「有没有回来看它」，
    # 由 pet_service 在 /api/pet 里维护，和打卡用的 streak 是两套口径。
    pet_species: Mapped[str] = mapped_column(String(32), default="hedgehog")
    pet_name: Mapped[str] = mapped_column(String(32), default="")
    last_login_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    login_streak: Mapped[int] = mapped_column(Integer, default=0)
    best_login_streak: Mapped[int] = mapped_column(Integer, default=0)
    # 喂食功能已下线，这两列只为兼容老库保留，不再读写。
    pet_last_fed: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pet_feed_streak: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # 子表的外键本身带 ON DELETE CASCADE，删用户时交给数据库处理即可。
    # 不写 passive_deletes 的话 SQLAlchemy 会先把 user_id 置 NULL，
    # 而这两列是 NOT NULL，删除会直接 IntegrityError。
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
