from __future__ import annotations

import json
import random
from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.gamification import XpRecord
from app.models.learning import UserVocabulary, Vocabulary
from app.models.user import User
from app.models.wordbook import (
    ContributionRecord,
    DailyTask,
    WordQuizSession,
    Wordbook,
    WordStudyLog,
)
from app.services import gamification_service

XP_RULES = {
    "word_review": 2,
    "word_correct": 3,
    "word_new": 5,
    "scenario_complete": 30,
    "article_read": 15,
    "reading_complete": 20,
    "daily_task_item": 10,
}

CONTRIBUTION_RULES = {
    "publish_article": 20,
    "publish_content": 15,
    "publish_scenario": 25,
    "forum_post": 5,
    "forum_reply": 2,
}

OVERACHIEVE_STEP = 0.25
OVERACHIEVE_XP = 15
OVERACHIEVE_CAP = 60

# 每次「记住了」提升的掌握度，三次即可把单词背出词书
MASTERY_STEP = 1 / 3

STUDY_ACTIONS = ("forget", "remember", "mastered")


def today_str() -> str:
    return date.today().isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def award_xp(db: Session, user: User, amount: int, source: str, ref: str = "") -> int:
    amount = int(amount)
    if amount <= 0:
        return 0
    db.add(XpRecord(user_id=user.id, amount=amount, source=source, ref=ref))
    user.xp = (user.xp or 0) + amount
    gamification_service.touch_streak(db, user)
    return amount


def award_contribution(
    db: Session,
    user: User,
    amount: int,
    reason: str,
    ref_type: str = "",
    ref_id: int | None = None,
    note: str = "",
) -> int:
    amount = int(amount)
    if amount <= 0:
        return 0
    db.add(
        ContributionRecord(
            user_id=user.id,
            amount=amount,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
        )
    )
    gamification_service.touch_streak(db, user)
    return amount


def award_publish_once(
    db: Session,
    user: User,
    *,
    content_id: int,
    amount: int,
    reason: str = "publish_content",
) -> int:
    existed = db.scalar(
        select(func.count(ContributionRecord.id)).where(
            ContributionRecord.user_id == user.id,
            ContributionRecord.ref_type == "user_content",
            ContributionRecord.ref_id == content_id,
        )
    )
    if existed:
        return 0
    return award_contribution(
        db, user, amount, reason, ref_type="user_content", ref_id=content_id
    )


def contribution_total(db: Session, user_id: int) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(ContributionRecord.amount), 0)).where(
            ContributionRecord.user_id == user_id
        )
    )
    return int(total or 0)


def get_or_create_daily_task(db: Session, user: User, task_date: str | None = None) -> DailyTask:
    task_date = task_date or today_str()
    task = db.scalar(
        select(DailyTask).where(DailyTask.user_id == user.id, DailyTask.task_date == task_date)
    )
    if task:
        return task

    lvl = max(1, user.level or 1)
    task = DailyTask(
        user_id=user.id,
        task_date=task_date,
        target_words=min(30 + (lvl - 1) * 7, 160),
        target_scenarios=1 if lvl < 5 else 2,
        target_articles=1,
        target_minutes=min(15 + (lvl - 1) * 2, 45),
    )
    db.add(task)
    db.flush()
    return task


def _user_of(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"user {user_id} not found")
    return user


def _item_ratios(task: DailyTask) -> list[float]:
    ratios = []
    if task.target_words:
        ratios.append(task.done_words / task.target_words)
    if task.target_scenarios:
        ratios.append(task.done_scenarios / task.target_scenarios)
    if task.target_articles:
        ratios.append(task.done_articles / task.target_articles)
    return ratios


def _completion_ratio(task: DailyTask) -> float:
    ratios = _item_ratios(task)
    if not ratios:
        return 0.0
    return min(ratios)


def _progress_ratio(task: DailyTask) -> float:
    ratios = _item_ratios(task)
    if not ratios:
        return 0.0
    # 单项超额不抬高整体进度，只有全部目标达成才到 100%
    return sum(min(1.0, ratio) for ratio in ratios) / len(ratios)


def _overachievement(task: DailyTask) -> float:
    return max([1.0, *_item_ratios(task)]) - 1.0


def settle_daily_task(db: Session, task: DailyTask) -> DailyTask:
    user = _user_of(db, task.user_id)

    for done, target, flag in (
        (task.done_words, task.target_words, "words"),
        (task.done_scenarios, task.target_scenarios, "scenarios"),
        (task.done_articles, task.target_articles, "articles"),
    ):
        if target and done >= target and not getattr(task, f"{flag}_xp_awarded"):
            award_xp(db, user, XP_RULES["daily_task_item"], f"daily_task_{flag}")
            task.xp_earned = (task.xp_earned or 0) + XP_RULES["daily_task_item"]
            setattr(task, f"{flag}_xp_awarded", True)

    if _completion_ratio(task) >= 1.0:
        if not task.is_complete:
            task.is_complete = True
            task.completed_at = _now()

        over = _overachievement(task)
        target_bonus = min(int(over / OVERACHIEVE_STEP) * OVERACHIEVE_XP, OVERACHIEVE_CAP)
        already = task.bonus_xp or 0
        if target_bonus > already:
            award_xp(db, user, target_bonus - already, "daily_bonus")
            task.bonus_xp = target_bonus

    db.flush()
    return task


def record_activity(
    db: Session,
    user: User,
    kind: str,
    amount: int = 1,
    xp: int | None = None,
    source: str | None = None,
    ref: str = "",
) -> dict:
    task = get_or_create_daily_task(db, user)

    if kind == "word":
        task.done_words += amount
    elif kind == "scenario":
        task.done_scenarios += amount
    elif kind == "article":
        task.done_articles += amount
    elif kind == "minutes":
        task.done_minutes += amount

    gained = 0
    if xp:
        gained = award_xp(db, user, xp * amount, source or kind, ref=ref)

    db.flush()
    settle_daily_task(db, task)
    db.flush()
    return {"xp_gained": gained, "task": serialize_daily_task(task)}


def record_reading(db: Session, user: User, *, kind: str, material_id: int) -> bool:
    ref = f"{kind}:{material_id}"
    day_start = datetime.combine(
        _now().date(), datetime.min.time(), tzinfo=timezone.utc
    )
    already = db.scalar(
        select(func.count(XpRecord.id)).where(
            XpRecord.user_id == user.id,
            XpRecord.source == "article",
            XpRecord.ref == ref,
            XpRecord.created_at >= day_start,
        )
    )
    if already:
        return False

    record_activity(
        db,
        user,
        "article",
        1,
        xp=XP_RULES["article_read"],
        source="article",
        ref=ref,
    )
    return True


def serialize_daily_task(task: DailyTask) -> dict:
    return {
        "date": task.task_date,
        "targets": {
            "words": task.target_words,
            "scenarios": task.target_scenarios,
            "articles": task.target_articles,
            "minutes": task.target_minutes,
        },
        "done": {
            "words": task.done_words,
            "scenarios": task.done_scenarios,
            "articles": task.done_articles,
            "minutes": task.done_minutes,
        },
        "xp_earned": task.xp_earned,
        "bonus_xp": task.bonus_xp,
        "awarded": {
            "words": bool(task.words_xp_awarded),
            "scenarios": bool(task.scenarios_xp_awarded),
            "articles": bool(task.articles_xp_awarded),
        },
        "is_complete": task.is_complete,
        "progress": round(_progress_ratio(task), 3),
        "overachievement": round(max(0.0, _overachievement(task)), 3),
    }


def parse_examples(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, str):
            out.append({"en": item, "zh": ""})
        elif isinstance(item, dict):
            out.append({"en": item.get("en", ""), "zh": item.get("zh", "")})
    return out


def serialize_word(word: Vocabulary, state: UserVocabulary | None) -> dict:
    return {
        "id": word.id,
        "word": word.word,
        "phonetic_uk": word.phonetic_uk or word.phonetic or "",
        "phonetic_us": word.phonetic_us or word.phonetic or "",
        "part_of_speech": word.part_of_speech or "",
        "meaning": word.meaning or "",
        "meaning_zh": word.meaning_zh or "",
        "example": word.example or "",
        "examples": parse_examples(word.examples_json),
        "level": word.level or "",
        "books": [b for b in (word.books or "").split(",") if b],
        "tags": [t for t in (word.tags or "").split(",") if t],
        "unit": word.unit or "",
        "audio_uk": word.audio_uk or "",
        "audio_us": word.audio_us or "",
        "in_vocabulary": bool(state.in_vocabulary) if state else False,
        "mastery": round(state.mastery, 3) if state else 0.0,
        "review_count": state.review_count if state else 0,
        "status": (state.status if state and state.status else "new"),
        "due_date": (state.due_date if state else "") or "",
    }


def _state_map(db: Session, user_id: int, word_ids: list[int]) -> dict[int, UserVocabulary]:
    if not word_ids:
        return {}
    rows = db.scalars(
        select(UserVocabulary).where(
            UserVocabulary.user_id == user_id,
            UserVocabulary.vocabulary_id.in_(word_ids),
        )
    ).all()
    return {r.vocabulary_id: r for r in rows}


def list_books(db: Session, user: User | None = None) -> list[dict]:
    books = db.scalars(select(Wordbook).order_by(Wordbook.order_index, Wordbook.id)).all()
    out = []
    for book in books:
        learned = 0
        if user is not None:
            learned = int(
                db.scalar(
                    select(func.count(func.distinct(Vocabulary.id)))
                    .select_from(Vocabulary)
                    .join(UserVocabulary, UserVocabulary.vocabulary_id == Vocabulary.id)
                    .where(
                        UserVocabulary.user_id == user.id,
                        Vocabulary.books.like(f"%{book.code}%"),
                    )
                )
                or 0
            )
        out.append(
            {
                "code": book.code,
                "name": book.name,
                "name_zh": book.name_zh,
                "description": book.description,
                "icon": book.icon,
                "level": book.level,
                "word_count": book.word_count,
                "learned": learned,
            }
        )
    return out


def list_words(
    db: Session,
    user: User | None,
    book: str | None = None,
    unit: str | None = None,
    offset: int = 0,
    limit: int = 20,
    only_my: bool = False,
    keyword: str | None = None,
) -> dict:
    stmt = select(Vocabulary)
    if book:
        stmt = stmt.where(Vocabulary.books.like(f"%{book}%"))
    if unit:
        stmt = stmt.where(Vocabulary.unit == unit)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            (Vocabulary.word.like(like))
            | (Vocabulary.meaning.like(like))
            | (Vocabulary.meaning_zh.like(like))
        )

    if only_my:
        stmt = stmt.join(UserVocabulary, UserVocabulary.vocabulary_id == Vocabulary.id).where(
            UserVocabulary.user_id == (user.id if user else -1),
            UserVocabulary.in_vocabulary.is_(True),
        )

    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(Vocabulary.order_index, Vocabulary.id)
        .offset(max(0, offset))
        .limit(max(1, min(limit, 100)))
    ).all()

    states = _state_map(db, user.id, [w.id for w in rows]) if user else {}
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [serialize_word(w, states.get(w.id)) for w in rows],
    }


def my_words_count(db: Session, user: User) -> int:
    return _count(db, _my_words_stmt(user))


def _my_words_stmt(user: User):
    return (
        select(Vocabulary)
        .join(UserVocabulary, UserVocabulary.vocabulary_id == Vocabulary.id)
        .where(
            UserVocabulary.user_id == user.id,
            UserVocabulary.in_vocabulary.is_(True),
        )
    )


def _quiz_answer_text(word: Vocabulary) -> str:
    return (word.meaning_zh or "").strip() or (word.meaning or "").strip() or "暂无释义"


def _quiz_options(db: Session, word: Vocabulary, correct: str) -> list[str]:
    rows = db.scalars(
        select(Vocabulary.meaning_zh)
        .where(Vocabulary.id != word.id, Vocabulary.meaning_zh != "")
        .order_by(func.random())
        .limit(80)
    ).all()
    options = [correct]
    seen = {correct}
    for text in rows:
        candidate = (text or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            options.append(candidate)
        if len(options) >= 4:
            break
    random.shuffle(options)
    return options


def get_quiz_session(db: Session, user: User) -> WordQuizSession | None:
    return db.scalar(select(WordQuizSession).where(WordQuizSession.user_id == user.id))


def _load_quiz_queue(db: Session, session: WordQuizSession) -> list[int]:
    try:
        raw = json.loads(session.queue_json or "[]")
    except (TypeError, ValueError):
        return []
    ids = [int(i) for i in raw if isinstance(i, (int, float, str)) and str(i).isdigit()]
    if not ids:
        return []
    existing = set(db.scalars(select(Vocabulary.id).where(Vocabulary.id.in_(ids))).all())
    return [i for i in ids if i in existing]


def serialize_quiz(db: Session, user: User, session: WordQuizSession) -> dict:
    queue = _load_quiz_queue(db, session)
    total = int(session.total or 0)
    answered = max(0, total - len(queue))
    finished = total > 0 and not queue

    question = None
    if queue:
        word = db.get(Vocabulary, queue[0])
        if word is not None:
            state = db.scalar(
                select(UserVocabulary).where(
                    UserVocabulary.user_id == user.id,
                    UserVocabulary.vocabulary_id == word.id,
                )
            )
            question = {
                "word": serialize_word(word, state),
                "options": _quiz_options(db, word, _quiz_answer_text(word)),
            }

    return {
        "active": total > 0 and not finished,
        "total": total,
        "remaining": len(queue),
        "answered": answered,
        "correct_count": answered,
        "wrong_count": int(session.wrong_count or 0),
        "finished": finished,
        "question": question,
    }


def start_quiz(db: Session, user: User, count: int = 10, mode: str = "fresh") -> dict:
    session = get_quiz_session(db, user)
    if mode == "resume" and session is not None and _load_quiz_queue(db, session):
        return serialize_quiz(db, user, session)

    stmt = _my_words_stmt(user)
    total = _count(db, stmt)
    take = max(0, min(int(count), total))
    if take == 0:
        return {
            "active": False,
            "total": 0,
            "remaining": 0,
            "answered": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "finished": False,
            "question": None,
        }

    queue = [w.id for w in db.scalars(stmt.order_by(func.random()).limit(take)).all()]
    if session is None:
        session = WordQuizSession(user_id=user.id)
        db.add(session)
    session.total = len(queue)
    session.queue_json = json.dumps(queue)
    session.correct_count = 0
    session.wrong_count = 0
    session.started_at = _now()
    session.updated_at = _now()
    db.flush()
    return serialize_quiz(db, user, session)


def answer_quiz(db: Session, user: User, word_id: int, choice: str) -> dict | None:
    session = get_quiz_session(db, user)
    if session is None:
        return None
    queue = _load_quiz_queue(db, session)
    if word_id not in queue:
        return None
    word = db.get(Vocabulary, word_id)
    if word is None:
        return None

    correct_text = _quiz_answer_text(word)
    is_correct = (choice or "").strip() == correct_text

    queue.remove(word_id)
    if is_correct:
        apply_study_answer(db, user, word, "remember")
    else:
        queue.append(word_id)
        session.wrong_count = int(session.wrong_count or 0) + 1
        apply_study_answer(db, user, word, "forget")

    session.queue_json = json.dumps(queue)
    session.correct_count = max(0, int(session.total or 0) - len(queue))
    session.updated_at = _now()
    db.flush()
    return {
        "correct": is_correct,
        "answer": correct_text,
        "session": serialize_quiz(db, user, session),
    }


def reset_quiz(db: Session, user: User) -> None:
    session = get_quiz_session(db, user)
    if session is not None:
        db.delete(session)


def get_word_model(db: Session, word_id: int) -> Vocabulary | None:
    return db.get(Vocabulary, word_id)


def get_word(db: Session, user: User | None, word_id: int) -> dict | None:
    word = db.get(Vocabulary, word_id)
    if word is None:
        return None
    state = None
    if user:
        state = db.scalar(
            select(UserVocabulary).where(
                UserVocabulary.user_id == user.id,
                UserVocabulary.vocabulary_id == word_id,
            )
        )
    return serialize_word(word, state)


def _get_or_create_state(
    db: Session, user: User, word: Vocabulary, source: str = "wordbook"
) -> UserVocabulary:
    state = db.scalar(
        select(UserVocabulary).where(
            UserVocabulary.user_id == user.id, UserVocabulary.vocabulary_id == word.id
        )
    )
    if state:
        return state
    # 背词只记录学习状态，不代表用户把这个词收进了「我的词库」
    state = UserVocabulary(
        user_id=user.id,
        vocabulary_id=word.id,
        source=source,
        book_code=(word.books or "").split(",")[0] if word.books else "",
        mastery=0.0,
        in_vocabulary=False,
    )
    db.add(state)
    db.flush()
    return state


def _random_queue_order(db: Session, word: Vocabulary) -> int:
    """在所属词书的顺序范围内取一个随机位置，让单词穿插回队列。"""
    book = (word.books or "").split(",")[0]
    stmt = select(func.min(Vocabulary.order_index), func.max(Vocabulary.order_index))
    if book:
        stmt = stmt.where(Vocabulary.books.like(f"%{book}%"))
    else:
        stmt = stmt.where(Vocabulary.id == word.id)
    low, high = db.execute(stmt).one()
    low = int(low or 0)
    high = int(high if high is not None else low)
    if high <= low:
        return low
    return random.randint(low, high)


def add_to_vocabulary(db: Session, user: User, word_id: int, source: str = "wordbook") -> dict | None:
    word = db.get(Vocabulary, word_id)
    if word is None:
        return None
    existed = db.scalar(
        select(UserVocabulary).where(
            UserVocabulary.user_id == user.id, UserVocabulary.vocabulary_id == word.id
        )
    )
    state = _get_or_create_state(db, user, word, source=source)
    state.in_vocabulary = True
    if existed is None:
        award_xp(db, user, XP_RULES["word_new"], "word_new")
        record_activity(db, user, "word", 1)
    db.flush()
    return serialize_word(word, state)


def remove_from_vocabulary(db: Session, user: User, word_id: int) -> dict | None:
    word = db.get(Vocabulary, word_id)
    if word is None:
        return None
    state = db.scalar(
        select(UserVocabulary).where(
            UserVocabulary.user_id == user.id,
            UserVocabulary.vocabulary_id == word_id,
        )
    )
    if state is None or not state.in_vocabulary:
        return None
    state.in_vocabulary = False
    db.flush()
    return serialize_word(word, state)


def review_word(db: Session, user: User, word_id: int, correct: bool) -> dict | None:
    word = db.get(Vocabulary, word_id)
    if word is None:
        return None
    payload = apply_study_answer(db, user, word, "remember" if correct else "forget")
    payload["correct"] = correct
    return payload


def _words_studied_today(db: Session, user_id: int, task_date: str) -> int:
    return int(
        db.scalar(
            select(func.count(func.distinct(WordStudyLog.vocabulary_id))).where(
                WordStudyLog.user_id == user_id, WordStudyLog.study_date == task_date
            )
        )
        or 0
    )


def sync_study_progress(db: Session, user: User, task: DailyTask | None = None) -> DailyTask:
    task = task or get_or_create_daily_task(db, user)
    task.done_words = max(
        task.done_words or 0, _words_studied_today(db, user.id, task.task_date)
    )
    db.flush()
    settle_daily_task(db, task)
    db.flush()
    return task


def _book_filter(stmt, book: str | None):
    if book:
        return stmt.where(Vocabulary.books.like(f"%{book}%"))
    return stmt


def _deck_order():
    return (
        func.coalesce(UserVocabulary.queue_order, Vocabulary.order_index),
        Vocabulary.id,
    )


def _deck_stmt(user: User, book: str | None):
    """词书里所有还没背出去的单词：没有记录，或还没到 mastered。"""
    stmt = (
        select(Vocabulary)
        .outerjoin(
            UserVocabulary,
            (UserVocabulary.vocabulary_id == Vocabulary.id)
            & (UserVocabulary.user_id == user.id),
        )
        .where(
            or_(
                UserVocabulary.id.is_(None),
                func.coalesce(UserVocabulary.status, "new") != "mastered",
            )
        )
    )
    return _book_filter(stmt, book)


def _count(db: Session, stmt) -> int:
    return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def study_summary(db: Session, user: User, book: str | None = None) -> dict:
    task = get_or_create_daily_task(db, user)
    mastered = int(
        db.scalar(
            select(func.count())
            .select_from(UserVocabulary)
            .where(UserVocabulary.user_id == user.id, UserVocabulary.status == "mastered")
        )
        or 0
    )
    target = task.target_words or 0
    done = task.done_words or 0
    return {
        "date": task.task_date,
        "book": book or "",
        "target": target,
        "done": done,
        "remaining": max(0, target - done),
        "available": _count(db, _deck_stmt(user, book)),
        "mastered": mastered,
    }


def study_queue(
    db: Session,
    user: User,
    book: str | None = None,
    limit: int | None = None,
) -> dict:
    take = max(1, min(int(limit), 100)) if limit else 20
    stmt = _deck_stmt(user, book)
    words = list(db.scalars(stmt.order_by(*_deck_order()).limit(take)).all())
    states = _state_map(db, user.id, [w.id for w in words])
    return {
        "book": book or "",
        "remaining": _count(db, _deck_stmt(user, book)),
        "items": [serialize_word(w, states.get(w.id)) for w in words],
    }


def apply_study_answer(
    db: Session,
    user: User,
    word: Vocabulary,
    action: str,
    book_code: str = "",
) -> dict:
    state = _get_or_create_state(db, user, word)
    if action not in STUDY_ACTIONS:
        action = "remember"

    first_seen = not state.is_new_seen
    log_mode = "new" if first_seen else "review"
    state.is_new_seen = True
    state.review_count = (state.review_count or 0) + 1
    state.exposure_count = (state.exposure_count or 0) + 1
    state.last_reviewed = _now()
    if book_code:
        state.book_code = book_code

    if action == "mastered":
        # 已掌握：掌握度拉满并移出词书
        state.status = "mastered"
        state.mastery = 1.0
        state.queue_order = None
    elif action == "remember":
        # 记住了只加掌握度，加满三次才移出词书，否则换个随机位置继续出现
        state.mastery = min(1.0, (state.mastery or 0.0) + MASTERY_STEP)
        if state.mastery >= 1.0 - 1e-9:
            state.mastery = 1.0
            state.status = "mastered"
            state.queue_order = None
        else:
            state.status = "learning"
            state.queue_order = _random_queue_order(db, word)
    else:
        # 没记住：掌握度不变，换个随机位置继续出现
        state.status = "learning"
        state.queue_order = _random_queue_order(db, word)

    if action != "forget":
        state.correct_count = (state.correct_count or 0) + 1

    xp = XP_RULES["word_review"]
    if action != "forget":
        xp += XP_RULES["word_correct"]
    if first_seen:
        xp += XP_RULES["word_new"]
    award_xp(db, user, xp, "word_study")

    db.add(
        WordStudyLog(
            user_id=user.id,
            vocabulary_id=word.id,
            book_code=state.book_code or book_code or "",
            mode=log_mode,
            action=action,
            study_date=today_str(),
        )
    )
    db.flush()

    task = sync_study_progress(db, user)

    payload = serialize_word(word, state)
    payload.update(
        {
            "action": action,
            "mode": log_mode,
            "xp_gained": xp,
            "task": serialize_daily_task(task),
        }
    )
    return payload


LEADERBOARD_KINDS = ("xp", "streak", "contribution")


def leaderboard(db: Session, kind: str = "xp", limit: int = 50, me: User | None = None) -> dict:
    kind = kind if kind in LEADERBOARD_KINDS else "xp"
    limit = max(1, min(int(limit), 100))

    if kind == "contribution":
        total = func.coalesce(func.sum(ContributionRecord.amount), 0)
        rows = db.execute(
            select(User.id, User.username, User.avatar, total.label("score"))
            .join(ContributionRecord, ContributionRecord.user_id == User.id)
            .group_by(User.id)
            .order_by(total.desc())
            .limit(limit)
        ).all()
        entries = [
            {
                "user_id": r.id,
                "username": r.username,
                "avatar": r.avatar,
                "score": int(r.score or 0),
            }
            for r in rows
        ]
    elif kind == "streak":
        rows = db.scalars(
            select(User)
            .order_by(User.streak.desc(), User.longest_streak.desc(), User.id)
            .limit(limit)
        ).all()
        entries = [
            {
                "user_id": u.id,
                "username": u.username,
                "avatar": u.avatar,
                "score": u.streak or 0,
                "longest": u.longest_streak or 0,
            }
            for u in rows
        ]
    else:
        rows = db.scalars(select(User).order_by(User.xp.desc(), User.id).limit(limit)).all()
        entries = [
            {
                "user_id": u.id,
                "username": u.username,
                "avatar": u.avatar,
                "score": u.xp or 0,
                "level": u.level,
            }
            for u in rows
        ]

    for i, entry in enumerate(entries, start=1):
        entry["rank"] = i

    mine = None
    if me is not None:
        if kind == "contribution":
            my_score = contribution_total(db, me.id)
            ahead = db.scalar(
                select(func.count()).select_from(
                    select(ContributionRecord.user_id)
                    .group_by(ContributionRecord.user_id)
                    .having(func.sum(ContributionRecord.amount) > my_score)
                    .subquery()
                )
            )
        elif kind == "streak":
            my_score = me.streak or 0
            ahead = db.scalar(select(func.count()).select_from(User).where(User.streak > my_score))
        else:
            my_score = me.xp or 0
            ahead = db.scalar(select(func.count()).select_from(User).where(User.xp > my_score))
        mine = {
            "rank": int(ahead or 0) + 1,
            "score": my_score,
            "in_top": any(e["user_id"] == me.id for e in entries),
        }

    return {"kind": kind, "entries": entries, "me": mine}
