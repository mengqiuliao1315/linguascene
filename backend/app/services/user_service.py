"""账号标识（用户名/邮箱）的公共校验。

管理员创建账号与用户自助改名走的是同一条唯一性规则，逻辑放在这里，
避免两处判断逐渐走偏。
"""

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.user import User


def ensure_identifiers_available(
    db: Session,
    *,
    username: str | None = None,
    email: str | None = None,
    exclude_user_id: int | None = None,
) -> None:
    """用户名/邮箱若已被别的账号占用就抛 400。

    exclude_user_id 用于更新场景：账号自己当前的值当然算"已存在"，
    要排除掉，否则改名时只要带了原值就会被误判为冲突。
    """
    conditions = []
    if username:
        conditions.append(User.username == username)
    if email:
        conditions.append(User.email == email)
    if not conditions:
        return

    stmt = select(User).where(or_(*conditions))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)

    clash = db.execute(stmt).scalars().first()
    if not clash:
        return

    if username and clash.username == username:
        raise HTTPException(status_code=400, detail="用户名已被使用")
    raise HTTPException(status_code=400, detail="邮箱已被使用")
