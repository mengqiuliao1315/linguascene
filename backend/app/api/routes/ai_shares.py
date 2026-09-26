from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.ai_settings import (
    AiShareIn,
    AiShareListOut,
    AiShareOut,
    AiSharePromptOut,
    AiShareUpdateIn,
)
from app.services import ai_config_service

router = APIRouter(prefix="/api/ai-shares", tags=["ai-shares"])


def _share_list(db: Session, user: User) -> AiShareListOut:
    adoption = ai_config_service.get_adoption(db, user)
    return AiShareListOut(
        mine=[
            AiShareOut.model_validate(s)
            for s in ai_config_service.my_shares_out(db, user)
        ],
        available=[
            AiShareOut.model_validate(s)
            for s in ai_config_service.available_shares_out(db, user)
        ],
        adopted_id=adoption.share_id if adoption else None,
    )


@router.get("", response_model=AiShareListOut)
def list_shares(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiShareListOut:
    """我分享出去的 + 别人分享给我可用的 + 我当前采纳的那条。"""
    return _share_list(db, user)


@router.post("", response_model=AiShareOut)
def create_share(
    payload: AiShareIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiShareOut:
    config = ai_config_service.get_config(db, user, payload.config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    if ai_config_service.config_provider(config) is None:
        raise HTTPException(status_code=400, detail="这条供应商还没配置好，先补全地址、Key 与模型")

    models = ai_config_service.load_models(config.models)
    if not models:
        raise HTTPException(status_code=400, detail="这条供应商还没有模型")
    api_key = ai_config_service.decrypt_config_key(config) or ""

    try:
        share = ai_config_service.create_share(
            db,
            user,
            title=payload.title,
            base_url=config.base_url,
            api_key=api_key,
            api_format=config.api_format,
            models=models,
            active_model=config.active_model,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    db.refresh(share)
    return AiShareOut.model_validate(ai_config_service.share_out(db, share, user, 0))


@router.patch("/{share_id}", response_model=AiShareOut)
def update_share(
    share_id: int,
    payload: AiShareUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiShareOut:
    """开关分享：关掉后不再推送给别人，记录保留。只能操作自己的。"""
    share = ai_config_service.get_share(db, share_id)
    if share is None or share.owner_id != user.id:
        raise HTTPException(status_code=404, detail="分享不存在")

    ai_config_service.set_share_active(db, share, payload.is_active)
    db.commit()
    db.refresh(share)
    counts = ai_config_service.adoption_counts(db, [share.id])
    return AiShareOut.model_validate(
        ai_config_service.share_out(db, share, user, counts.get(share.id, 0))
    )


@router.delete("/{share_id}", response_model=AiShareListOut)
def delete_share(
    share_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiShareListOut:
    """彻底删除分享：其他人立即看不到，采纳/关闭记录一并清掉。"""
    share = ai_config_service.get_share(db, share_id)
    if share is None or share.owner_id != user.id:
        raise HTTPException(status_code=404, detail="分享不存在")

    ai_config_service.delete_share(db, share)
    db.commit()
    return _share_list(db, user)


@router.post("/{share_id}/adopt", response_model=AiShareOut)
def adopt_share(
    share_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiShareOut:
    """采纳这条分享，并把当前选择切到它，之后的 AI 调用走它。"""
    share = ai_config_service.get_share(db, share_id)
    if share is None:
        raise HTTPException(status_code=404, detail="分享不存在")
    try:
        ai_config_service.adopt_share(db, user, share)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    db.refresh(share)
    counts = ai_config_service.adoption_counts(db, [share.id])
    return AiShareOut.model_validate(
        ai_config_service.share_out(db, share, user, counts.get(share.id, 0))
    )


@router.post("/{share_id}/dismiss", response_model=AiSharePromptOut)
def dismiss_share(
    share_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiSharePromptOut:
    """关闭这条分享的弹窗，之后不再对当前用户推送。"""
    share = ai_config_service.get_share(db, share_id)
    if share is None:
        raise HTTPException(status_code=404, detail="分享不存在")

    ai_config_service.dismiss_share(db, user, share)
    db.commit()
    return AiSharePromptOut(available=False, share=None, reason="已关闭")


@router.get("/prompt", response_model=AiSharePromptOut)
def share_prompt(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiSharePromptOut:
    """登录后弹窗：是否有值得推荐的分享。"""
    return AiSharePromptOut.model_validate(ai_config_service.share_prompt(db, user))
