from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.vocabulary import ReviewRequest, SaveVocabularyRequest, VocabularyOut
from app.services import gamification_service, levels, vocabulary_service

router = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])


@router.get("", response_model=list[VocabularyOut])
def list_vocabulary(
    due_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[VocabularyOut]:
    rows = vocabulary_service.list_words(db, user, due_only=due_only)
    return [VocabularyOut.model_validate(r) for r in rows]


@router.get("/review-today", response_model=list[VocabularyOut])
def review_today(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[VocabularyOut]:
    rows = vocabulary_service.list_words(db, user, due_only=True)
    return [VocabularyOut.model_validate(r) for r in rows]


@router.post("/save", response_model=VocabularyOut, status_code=201)
def save_vocabulary(
    payload: SaveVocabularyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VocabularyOut:
    record, created = vocabulary_service.save_word(
        db,
        user,
        word=payload.word,
        meaning=payload.meaning,
        phonetic=payload.phonetic,
        example=payload.example,
        level=payload.level,
        source=payload.source,
    )
    if created:
        gamification_service.award_xp(db, user, levels.XP_REWARDS["new_word"], "new_word")
    db.commit()

    rows = vocabulary_service.list_words(db, user)
    match = next((r for r in rows if r["word"] == record.vocabulary.word), None)
    if not match:
        raise HTTPException(status_code=500, detail="保存失败")
    return VocabularyOut.model_validate(match)


@router.post("/{vocabulary_id}/review")
def review_vocabulary(
    vocabulary_id: int,
    payload: ReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    result = vocabulary_service.review_word(db, user, vocabulary_id, payload.quality)
    if result is None:
        raise HTTPException(status_code=404, detail="单词不在词库中")

    gamification_service.award_xp(db, user, levels.XP_REWARDS["review"], "review")
    db.commit()
    return result


@router.delete("/{vocabulary_id}", status_code=204)
def delete_vocabulary(
    vocabulary_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if not vocabulary_service.delete_word(db, user, vocabulary_id):
        raise HTTPException(status_code=404, detail="单词不在词库中")
    db.commit()
