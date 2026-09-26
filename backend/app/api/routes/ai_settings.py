from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.provider import AIProviderError, probe_provider_detail
from app.api.deps import get_current_user, get_user_provider
from app.core.database import get_db
from app.models.user import User
from app.schemas.ai_settings import (
    AiActiveIn,
    AiConnectionResult,
    AiModelListIn,
    AiModelListOut,
    AiProviderConfigIn,
    UserAiStatusOut,
)
from app.services import ai_config_service

router = APIRouter(prefix="/api/ai-settings", tags=["ai-settings"])


def _status(db: Session, user: User) -> UserAiStatusOut:
    return UserAiStatusOut.model_validate(ai_config_service.user_ai_status(db, user))


def _reload(db: Session, user: User) -> UserAiStatusOut:
    db.commit()
    db.refresh(user)
    return _status(db, user)


@router.get("", response_model=UserAiStatusOut)
def get_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserAiStatusOut:
    return _status(db, user)


@router.post("/configs", response_model=UserAiStatusOut)
def create_config(
    payload: AiProviderConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserAiStatusOut:
    if not payload.api_key.strip():
        raise HTTPException(status_code=400, detail="请填写 API Key")
    if not payload.models:
        raise HTTPException(status_code=400, detail="请至少添加一个模型")
    try:
        ai_config_service.validate_base_url(payload.base_url, payload.api_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    config = ai_config_service.create_config(
        db,
        user,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        api_format=payload.api_format,
        models=payload.models,
        active_model=payload.active_model,
    )
    ai_config_service.set_active_config(db, user, config)
    return _reload(db, user)


@router.put("/configs/{config_id}", response_model=UserAiStatusOut)
def update_config(
    config_id: int,
    payload: AiProviderConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserAiStatusOut:
    config = ai_config_service.get_config(db, user, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    if not payload.models:
        raise HTTPException(status_code=400, detail="请至少添加一个模型")
    try:
        ai_config_service.validate_base_url(payload.base_url, payload.api_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ai_config_service.update_config(
        db,
        config,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        api_format=payload.api_format,
        models=payload.models,
        active_model=payload.active_model,
    )
    return _reload(db, user)


@router.delete("/configs/{config_id}", response_model=UserAiStatusOut)
def delete_config(
    config_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserAiStatusOut:
    config = ai_config_service.get_config(db, user, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="供应商不存在")

    ai_config_service.delete_config(db, config)
    if user.ai_active_config_id == config_id:
        user.ai_active_config_id = None
    return _reload(db, user)


@router.patch("/active", response_model=UserAiStatusOut)
def set_active(
    payload: AiActiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserAiStatusOut:
    """切换当前使用的模型：选自己的某条供应商，或选采纳的某条分享。"""
    if payload.config_id is not None:
        config = ai_config_service.get_config(db, user, payload.config_id)
        if config is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if ai_config_service.config_provider(config) is None:
            raise HTTPException(status_code=400, detail="这条供应商还没配置好")
        ai_config_service.set_active_config(db, user, config)

    elif payload.share_id is not None:
        share = ai_config_service.get_share(db, payload.share_id)
        if share is None:
            raise HTTPException(status_code=404, detail="分享不存在")
        try:
            ai_config_service.adopt_share(db, user, share)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    else:
        user.ai_active_config_id = None
        user.ai_active_share_id = None

    return _reload(db, user)


def _resolve_key(
    db: Session,
    user: User,
    payload: AiModelListIn,
) -> str:
    if payload.api_key:
        return payload.api_key
    if payload.config_id is not None:
        config = ai_config_service.get_config(db, user, payload.config_id)
        if config is not None:
            return ai_config_service.decrypt_config_key(config) or ""
    return ""


@router.post("/test", response_model=AiConnectionResult)
def test_credential(
    payload: AiModelListIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiConnectionResult:
    api_key = _resolve_key(db, user, payload)
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")

    try:
        provider = ai_config_service.build_provider(
            base_url=payload.base_url,
            api_key=api_key,
            model=payload.model,
            api_format=payload.api_format,
        )
    except AIProviderError as exc:
        return AiConnectionResult(success=False, message=str(exc), status="fail")

    outcome = probe_provider_detail(provider)
    return AiConnectionResult(
        success=outcome.success,
        message=outcome.message,
        status=outcome.status,
        suggested_models=outcome.suggested_models,
    )


@router.post("/models", response_model=AiModelListOut)
def list_models(
    payload: AiModelListIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiModelListOut:
    """拉取该接入地址下的模型列表，供前端下拉选择。"""
    api_key = _resolve_key(db, user, payload)
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")

    try:
        models = ai_config_service.list_provider_models(
            base_url=payload.base_url,
            api_key=api_key,
            api_format=payload.api_format,
        )
    except AIProviderError as exc:
        return AiModelListOut(success=False, message=str(exc))
    return AiModelListOut(
        success=True, message=f"获取到 {len(models)} 个模型", models=models
    )


@router.get("/active", response_model=AiConnectionResult)
def active_provider(
    provider=Depends(get_user_provider),
) -> AiConnectionResult:
    """当前这条请求实际会用哪个模型，供设置页回显。"""
    return AiConnectionResult(success=True, message=provider.label)
