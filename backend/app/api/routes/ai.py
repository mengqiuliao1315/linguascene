from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.schemas import TranslationOut
from app.api.deps import get_current_user, get_user_provider
from app.core.database import get_db
from app.models.user import User
from app.schemas.content import (
    SentenceAnalysisRequest,
    TranslateRequest,
    WordExplanationOut,
)
from app.services import content_service

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/explain-word", response_model=WordExplanationOut)
def explain_word(
    payload: TranslateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> WordExplanationOut:
    result = content_service.explain_word(
        payload.text.strip(),
        payload.context or payload.text,
        user.cefr_level,
        db,
        provider,
        fast=payload.fast,
    )
    return WordExplanationOut.model_validate(result)


@router.post("/analyze-sentence")
def analyze_sentence(
    payload: SentenceAnalysisRequest,
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> dict:
    return content_service.analyze_sentence(
        payload.sentence, user.cefr_level, payload.context, provider
    )


@router.post("/translate", response_model=TranslationOut)
def translate(
    payload: TranslateRequest,
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> TranslationOut:
    """只要一句中文译文。

    对话气泡下的「翻译」按钮走这里，而不是 /analyze-sentence——后者要一并
    产出主干、搭配、语法，模型输出多好几倍，等待也久好几倍。
    """
    return TranslationOut(
        translation=content_service.translate_text(payload.text, provider)
    )
