"""个人词库与间隔复习。

第一版使用简化的 SM-2 思路：掌握度决定下次复习间隔，不引入机器学习。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.learning import UserVocabulary, Vocabulary
from app.models.user import User

# 掌握度 -> 下次复习间隔（天）
INTERVALS = [(0.3, 1), (0.5, 2), (0.7, 4), (0.85, 7), (1.01, 15)]


def _next_interval(mastery: float) -> int:
    for threshold, days in INTERVALS:
        if mastery < threshold:
            return days
    return 15


def get_or_create_word(
    db: Session,
    word: str,
    meaning: str = "",
    phonetic: str = "",
    example: str = "",
    level: str = "B1",
) -> Vocabulary:
    normalized = word.strip().lower()
    existing = db.execute(
        select(Vocabulary).where(Vocabulary.word == normalized)
    ).scalar_one_or_none()
    if existing:
        return existing

    vocab = Vocabulary(
        word=normalized,
        meaning=meaning,
        phonetic=phonetic,
        example=example,
        level=level,
    )
    db.add(vocab)
    db.flush()
    return vocab


def save_word(
    db: Session,
    user: User,
    *,
    word: str,
    meaning: str = "",
    phonetic: str = "",
    example: str = "",
    level: str = "B1",
    source: str = "reading",
) -> tuple[UserVocabulary, bool]:
    """返回 (记录, 是否新增)。重复加入不会重复计数。"""
    vocab = get_or_create_word(db, word, meaning, phonetic, example, level)
    existing = db.execute(
        select(UserVocabulary).where(
            UserVocabulary.user_id == user.id, UserVocabulary.vocabulary_id == vocab.id
        )
    ).scalar_one_or_none()
    if existing:
        return existing, False

    now = datetime.now(timezone.utc)
    record = UserVocabulary(
        user_id=user.id,
        vocabulary_id=vocab.id,
        source=source,
        mastery=0.3,
        review_count=0,
        next_review=now + timedelta(days=1),
    )
    db.add(record)
    db.flush()
    return record, True


def list_words(db: Session, user: User, due_only: bool = False) -> list[dict]:
    query = (
        select(UserVocabulary, Vocabulary)
        .join(Vocabulary, Vocabulary.id == UserVocabulary.vocabulary_id)
        .where(UserVocabulary.user_id == user.id)
        .order_by(UserVocabulary.created_at.desc())
    )
    rows = db.execute(query).all()

    now = datetime.now(timezone.utc)
    result = []
    for record, vocab in rows:
        if due_only:
            next_review = record.next_review
            if next_review is not None and next_review.tzinfo is None:
                next_review = next_review.replace(tzinfo=timezone.utc)
            if next_review is not None and next_review > now:
                continue
        result.append(
            {
                "id": vocab.id,
                "word": vocab.word,
                "phonetic": vocab.phonetic,
                "meaning": vocab.meaning,
                "example": vocab.example,
                "level": vocab.level,
                "mastery": record.mastery,
                "review_count": record.review_count,
                "source": record.source,
                "next_review": record.next_review,
            }
        )
    return result


def review_word(db: Session, user: User, vocabulary_id: int, quality: int) -> dict | None:
    """quality: 0 忘记 / 1 模糊 / 2 记得。掌握度与间隔随之调整。"""
    record = db.execute(
        select(UserVocabulary).where(
            UserVocabulary.user_id == user.id,
            UserVocabulary.vocabulary_id == vocabulary_id,
        )
    ).scalar_one_or_none()
    if not record:
        return None

    delta = {0: -0.2, 1: 0.05, 2: 0.15}.get(quality, 0.0)
    record.mastery = max(0.0, min(1.0, record.mastery + delta))
    record.review_count += 1
    if quality == 2:
        record.correct_count += 1

    now = datetime.now(timezone.utc)
    record.last_reviewed = now
    record.next_review = now + timedelta(days=_next_interval(record.mastery))
    db.flush()

    return {
        "word": record.vocabulary.word,
        "mastery": record.mastery,
        "next_review": record.next_review,
    }


def due_count(db: Session, user: User) -> int:
    return len(list_words(db, user, due_only=True))


def delete_word(db: Session, user: User, vocabulary_id: int) -> bool:
    record = db.execute(
        select(UserVocabulary).where(
            UserVocabulary.user_id == user.id,
            UserVocabulary.vocabulary_id == vocabulary_id,
        )
    ).scalar_one_or_none()
    if not record:
        return False
    db.delete(record)
    db.flush()
    return True
