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
