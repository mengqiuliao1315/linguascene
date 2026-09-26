from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_user_provider
from app.core.database import get_db
from app.core.storage import MAX_UPLOAD_BYTES
from app.core.uploads import read_limited
from app.models.user import User
from app.schemas.content import UserContentOut
from app.services import content_service, wordbook_service

router = APIRouter(prefix="/api/content", tags=["content"])


@router.post("/upload", response_model=UserContentOut, status_code=201)
async def upload_content(
    file: UploadFile | None = File(default=None),
    text: str = Form(default=""),
    title: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserContentOut:
    raw = await read_limited(file, MAX_UPLOAD_BYTES, too_large="文件超过 10MB 限制")
    try:
        content = content_service.create_user_content(
            db,
            user,
            title=title,
            filename=file.filename if file is not None else "",
            raw=raw,
            text=text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    wordbook_service.award_contribution(
        db, user, wordbook_service.CONTRIBUTION_RULES["publish_content"],
        "publish_content", ref_type="user_content", ref_id=content.id,
    )
    db.commit()
    return UserContentOut.model_validate(content_service.content_payload(content))


@router.get("", response_model=list[UserContentOut])
def list_content(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[UserContentOut]:
    rows = content_service.list_user_content(db, user)
    return [UserContentOut.model_validate(content_service.content_payload(c)) for c in rows]


@router.get("/{content_id}")
def get_content(
    content_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    content = content_service.get_user_content(db, user, content_id)
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")
    return {**content_service.content_payload(content), "content": content.content}


@router.post("/{content_id}/generate-learning-material")
def generate_material(
    content_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> dict:
    content = content_service.get_user_content(db, user, content_id)
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")

    payload = content_service.generate_learning_material(
        db, user, content, force, provider
    )
    db.commit()
    return payload
