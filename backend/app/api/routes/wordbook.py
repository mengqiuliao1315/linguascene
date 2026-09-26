from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import audio_service, wordbook_service

router = APIRouter(prefix="/api/wordbook", tags=["wordbook"])


class ReviewIn(BaseModel):
    correct: bool = True


class QuizStartIn(BaseModel):
    count: int = Field(default=10, ge=1, le=100)
    mode: str = Field(default="fresh", pattern="^(fresh|resume)$")


class QuizAnswerIn(BaseModel):
    word_id: int
    choice: str = Field(min_length=1, max_length=500)


class StudyAnswerIn(BaseModel):
    action: str = Field(pattern="^(forget|remember|mastered)$")
    book: str | None = None


class DailyTaskIn(BaseModel):
    target_words: int | None = Field(default=None, ge=1, le=300)
    target_scenarios: int | None = Field(default=None, ge=0, le=20)
    target_articles: int | None = Field(default=None, ge=0, le=20)
    target_minutes: int | None = Field(default=None, ge=1, le=600)


@router.get("/wordbooks")
def list_wordbooks(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    return {"items": wordbook_service.list_books(db, user)}


@router.get("/wordbooks/{code}/words")
def list_book_words(
    code: str,
    unit: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return wordbook_service.list_words(
        db,
        user,
        book=code,
        unit=unit,
        offset=offset,
        limit=limit,
        keyword=keyword,
    )


@router.get("/cards")
def list_cards(
    book: str | None = None,
    unit: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    only_my: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return wordbook_service.list_words(
        db,
        user,
        book=book,
        unit=unit,
        offset=offset,
        limit=limit,
        keyword=keyword,
        only_my=only_my,
    )


@router.get("/quiz")
def quiz_state(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """当前测验进度（没开始过则 active=false）。"""
    session = wordbook_service.get_quiz_session(db, user)
    if session is None:
        return {"active": False, "total": 0, "remaining": 0, "question": None}
    return wordbook_service.serialize_quiz(db, user, session)


@router.post("/quiz")
def quiz_start(
    payload: QuizStartIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """抽题开始测验；mode=resume 时接着上次没答完的题继续。"""
    data = wordbook_service.start_quiz(db, user, count=payload.count, mode=payload.mode)
    db.commit()
    return data


@router.post("/quiz/answer")
def quiz_answer(
    payload: QuizAnswerIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """作答一道题。答错会回到队尾，稍后重新出现。"""
    data = wordbook_service.answer_quiz(db, user, payload.word_id, payload.choice)
    if data is None:
        raise HTTPException(status_code=404, detail="这道题不在当前测验中")
    db.commit()
    return data


@router.delete("/quiz")
def quiz_reset(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """放弃当前测验，清掉保存的进度。"""
    wordbook_service.reset_quiz(db, user)
    db.commit()
    return {"ok": True}


@router.delete("/my/word/{word_id}")
def remove_my_word(
    word_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """把单词移出我的单词本（保留学习记录，只清 in_vocabulary 与收藏）。"""
    data = wordbook_service.remove_from_vocabulary(db, user, word_id)
    if data is None:
        raise HTTPException(status_code=404, detail="单词不在我的单词本中")
    db.commit()
    return data


@router.get("/word/{word_id}")
def get_word(
    word_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    data = wordbook_service.get_word(db, user, word_id)
    if data is None:
        raise HTTPException(status_code=404, detail="单词不存在")
    return data


@router.post("/word/{word_id}/collect")
def collect_word(
    word_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    data = wordbook_service.add_to_vocabulary(db, user, word_id)
    if data is None:
        raise HTTPException(status_code=404, detail="单词不存在")
    db.commit()
    return data


@router.post("/word/{word_id}/review")
def review_word(
    word_id: int,
    payload: ReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    data = wordbook_service.review_word(db, user, word_id, payload.correct)
    if data is None:
        raise HTTPException(status_code=404, detail="单词不存在")
    db.commit()
    return data


@router.get("/study/summary")
def study_summary(
    book: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    data = wordbook_service.study_summary(db, user, book=book)
    db.commit()
    return data


@router.get("/study/queue")
def study_queue(
    book: str | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return wordbook_service.study_queue(db, user, book=book, limit=limit)


@router.post("/word/{word_id}/study")
def study_answer(
    word_id: int,
    payload: StudyAnswerIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    word = wordbook_service.get_word_model(db, word_id)
    if word is None:
        raise HTTPException(status_code=404, detail="单词不存在")
    data = wordbook_service.apply_study_answer(
        db, user, word, payload.action, book_code=payload.book or ""
    )
    db.commit()
    return data


@router.get("/audio/{word}")
def word_audio(word: str, accent: str = "us"):
    path = audio_service.get_or_create(word, accent)
    if path is None:
        raise HTTPException(status_code=404, detail="该单词暂无音频，请使用浏览器朗读")
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)


@router.get("/daily-task")
def get_daily_task(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    task = wordbook_service.get_or_create_daily_task(db, user)
    db.commit()
    return wordbook_service.serialize_daily_task(task)


@router.put("/daily-task")
def update_daily_task(
    payload: DailyTaskIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    task = wordbook_service.get_or_create_daily_task(db, user)
    for field in (
        "target_words",
        "target_scenarios",
        "target_articles",
        "target_minutes",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(task, field, value)
    db.flush()
    wordbook_service.settle_daily_task(db, task)
    db.commit()
    return wordbook_service.serialize_daily_task(task)


@router.get("/leaderboard")
def leaderboard(
    type: str = Query("xp", pattern="^(xp|streak|contribution)$"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return wordbook_service.leaderboard(db, kind=type, limit=limit, me=user)


@router.get("/leaderboard/{kind}")
def leaderboard_kind(
    kind: str,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return wordbook_service.leaderboard(db, kind=kind, limit=limit, me=user)
