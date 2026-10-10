from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_user_provider
from app.core.database import get_db
from app.models.user import User
from app.schemas.content import (
    ArticleAnalysisOut,
    ArticleCardOut,
    ArticleDetailOut,
    SentenceAnalysisRequest,
    TranslateRequest,
    WordExplanationOut,
)
from app.services import content_service

router = APIRouter(prefix="/api/articles", tags=["articles"])


@router.get("", response_model=list[ArticleCardOut])
def list_articles(
    category: str | None = Query(default=None),
    level: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[ArticleCardOut]:
    rows = content_service.list_articles(db, category, level)
    return [ArticleCardOut.model_validate(a) for a in rows]


@router.get("/{article_id}", response_model=ArticleDetailOut)
def get_article(
    article_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ArticleDetailOut:
    article = content_service.get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    return ArticleDetailOut.model_validate(article)


@router.post("/{article_id}/analyze", response_model=ArticleAnalysisOut)
def analyze_article(
    article_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> ArticleAnalysisOut:
    article = content_service.get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")

    analysis = content_service.analyze_article(
        db, article, user.cefr_level, provider
    )
    db.commit()
    return ArticleAnalysisOut.model_validate(content_service.analysis_payload(analysis))


@router.post("/translate", response_model=WordExplanationOut)
def translate(
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


@router.post("/explain-sentence")
def explain_sentence(
    payload: SentenceAnalysisRequest,
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> dict:
    return content_service.analyze_sentence(
        payload.sentence, user.cefr_level, payload.context, provider
    )
