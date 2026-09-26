"""词书 / 单词卡 / 每日任务 / 贡献值 / 排行榜 业务逻辑。"""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta, timezone

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
    # 今日任务的三个子项各自完成时各发一次，见 settle_daily_task。
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

# 复习间隔（天）：答对一次前进一档，答错退回第一档。
REVIEW_STAGES = (1, 2, 4, 7, 15, 30, 60)

STUDY_MODES = ("new", "review")
STUDY_ACTIONS = ("forget", "remember", "mastered")


def today_str() -> str:
    return date.today().isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def award_xp(db: Session, user: User, amount: int, source: str) -> int:
    amount = int(amount)
    if amount <= 0:
        return 0
    db.add(XpRecord(user_id=user.id, amount=amount, source=source))
    user.xp = (user.xp or 0) + amount
    # 拿到经验就算当天有学习行为，热力图与连续打卡天数据此累计。
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
    # 发布内容同样算当天学习，发帖/评论/上传文章都走这里。
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
    """同一份内容只记一次贡献值。

    上传接口和「公布给大家」都会走到这里，同一个人对同一份内容
    反复公布不该反复加分。
    """
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
    target_new = min(10 + (lvl - 1) * 2, 40)
    target_review = min(20 + (lvl - 1) * 5, 120)
    task = DailyTask(
        user_id=user.id,
        task_date=task_date,
        # 背单词总目标 = 新学 + 复习，今日任务的「背单词」子项按这个总数结算
        target_words=target_new + target_review,
        target_scenarios=1 if lvl < 5 else 2,
        target_articles=1,
        target_minutes=min(15 + (lvl - 1) * 2, 45),
        target_new_words=target_new,
        target_review_words=target_review,
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
    """完成判定用最短板：三个子项都达标才算今日任务完成。"""
    ratios = _item_ratios(task)
    if not ratios:
        return 0.0
    return min(ratios)


def _progress_ratio(task: DailyTask) -> float:
    """进度条用平均值：否则某项为 0 时条子会一直空着，看起来像坏了。"""
    ratios = _item_ratios(task)
    if not ratios:
        return 0.0
    return sum(ratios) / len(ratios)


def _overachievement(task: DailyTask) -> float:
    return max([1.0, *_item_ratios(task)]) - 1.0


def settle_daily_task(db: Session, task: DailyTask) -> DailyTask:
    """结算每日任务：三个子项各自完成时各发 10 XP，超额奖励随进度补差。

    子项经验各自走一次性开关，重复调用安全。超额奖励不能在「刚完成」那一刻算——
    那时 done 恰好等于 target，超额比例必然是 0，之后再学也不会有奖励。所以这里
    把子项完成和超额分开：前者按开关发，后者按当前完成度重算并只补发差额。
    """
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
) -> dict:
    """记录一次学习行为：累加每日任务进度 + 发经验。"""
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
        gained = award_xp(db, user, xp * amount, source or kind)

    db.flush()
    settle_daily_task(db, task)
    db.flush()
    return {"xp_gained": gained, "task": serialize_daily_task(task)}


def record_reading(db: Session, user: User) -> bool:
    """打开一篇材料就算读过：每天只计一次，计入「读文章」并发经验。

    没有这层幂等，一天里反复打开同一篇材料会把每日任务的篇数灌满。
    """
    day_start = datetime.combine(
        _now().date(), datetime.min.time(), tzinfo=timezone.utc
    )
    already = db.scalar(
        select(func.count(XpRecord.id)).where(
            XpRecord.user_id == user.id,
            XpRecord.source == "article",
            XpRecord.created_at >= day_start,
        )
    )
    if already:
        return False

    record_activity(
        db, user, "article", 1, xp=XP_RULES["article_read"], source="article"
    )
    return True


def serialize_daily_task(task: DailyTask) -> dict:
    return {
        "date": task.task_date,
        "targets": {
            "words": task.target_words,
            "new_words": task.target_new_words,
            "review_words": task.target_review_words,
            "scenarios": task.target_scenarios,
            "articles": task.target_articles,
            "minutes": task.target_minutes,
        },
        "done": {
            "words": task.done_words,
            "new_words": task.done_new_words,
            "review_words": task.done_review_words,
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
            # 「我的单词本」只算真正收进来的词，删除后 in_vocabulary 置 false 就不再出现
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
    """我的单词本里的单词总数。"""
    return _count(db, _my_words_stmt(user))


def _my_words_stmt(user: User):
    """用户自己收进单词本的词（词书收藏、精读、划词翻译都会落到这里）。"""
    return (
        select(Vocabulary)
        .join(UserVocabulary, UserVocabulary.vocabulary_id == Vocabulary.id)
        .where(
            UserVocabulary.user_id == user.id,
            UserVocabulary.in_vocabulary.is_(True),
        )
    )


# ---------------------------------------------------------------------------
# 随机测验：选择题 + 可中断续做
# ---------------------------------------------------------------------------


def _quiz_answer_text(word: Vocabulary) -> str:
    """题目正确选项文案。释义优先用中文，缺失时退回 meaning（划词收进来的词常只有这个）。"""
    return (word.meaning_zh or "").strip() or (word.meaning or "").strip() or "暂无释义"


def _quiz_options(db: Session, word: Vocabulary, correct: str) -> list[str]:
    """生成 4 个中文选项：1 个正确释义 + 3 个来自词库其他词的中文释义。"""
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
    """读出待答队列，并剔除已被删除的单词。"""
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
    """开始或继续一轮测验。

    - mode="resume" 且已有未完成的记录：原样接着答
    - 否则重新从「我的单词本」随机抽 count 个词，覆盖旧记录
    """
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
    """作答一道题。答对出队，答错挪到队尾，直到队列空才算完成。"""
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
        apply_study_answer(db, user, word, "remember", mode="review")
    else:
        queue.append(word_id)
        session.wrong_count = int(session.wrong_count or 0) + 1
        apply_study_answer(db, user, word, "forget", mode="review")

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
    """按 id 取单词本体，供写接口复用（读接口用 get_word）。"""
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
    state = UserVocabulary(
        user_id=user.id,
        vocabulary_id=word.id,
        source=source,
        book_code=(word.books or "").split(",")[0] if word.books else "",
        in_vocabulary=True,
    )
    db.add(state)
    db.flush()
    return state


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
    """把单词移出「我的单词本」。

    只清 in_vocabulary，保留 UserVocabulary 行本身（掌握度、复习记录、
    学习流水都还在），这样误删后重新加入不会丢失学习进度。
    """
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


# ---------------------------------------------------------------------------
# 背单词：新学 / 复习队列
# ---------------------------------------------------------------------------


def _study_counts(db: Session, user_id: int, task_date: str) -> tuple[int, int]:
    """今日已学的新词数、已复习的词数（按词去重）。"""
    rows = db.execute(
        select(WordStudyLog.mode, func.count(func.distinct(WordStudyLog.vocabulary_id)))
        .where(WordStudyLog.user_id == user_id, WordStudyLog.study_date == task_date)
        .group_by(WordStudyLog.mode)
    ).all()
    counts = {mode: int(total or 0) for mode, total in rows}
    return counts.get("new", 0), counts.get("review", 0)


def _book_filter(stmt, book: str | None):
    if book:
        return stmt.where(Vocabulary.books.like(f"%{book}%"))
    return stmt


def _new_queue_stmt(user: User, book: str | None):
    """还没学过的词：没有学习记录，或记录仍是 new 且没真正学过。"""
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
                UserVocabulary.status == "new",
            ),
            or_(
                UserVocabulary.is_new_seen.is_(None),
                UserVocabulary.is_new_seen.is_(False),
            ),
        )
    )
    return _book_filter(stmt, book)


def _review_queue_stmt(user: User, book: str | None):
    """到期待复习的词：learning / review 且 due_date 已到。mastered 永不出现。"""
    stmt = (
        select(Vocabulary)
        .join(UserVocabulary, UserVocabulary.vocabulary_id == Vocabulary.id)
        .where(
            UserVocabulary.user_id == user.id,
            UserVocabulary.status.in_(("learning", "review")),
            UserVocabulary.due_date != "",
            UserVocabulary.due_date <= today_str(),
        )
    )
    return _book_filter(stmt, book)


def _count(db: Session, stmt) -> int:
    return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def study_summary(db: Session, user: User, book: str | None = None) -> dict:
    task = get_or_create_daily_task(db, user)
    new_done, review_done = _study_counts(db, user.id, task.task_date)
    mastered = int(
        db.scalar(
            select(func.count())
            .select_from(UserVocabulary)
            .where(UserVocabulary.user_id == user.id, UserVocabulary.status == "mastered")
        )
        or 0
    )
    return {
        "date": task.task_date,
        "book": book or "",
        "new": {
            "target": task.target_new_words,
            "done": new_done,
            "remaining": max(0, task.target_new_words - new_done),
            "available": _count(db, _new_queue_stmt(user, book)),
        },
        "review": {
            "target": task.target_review_words,
            "done": review_done,
            "remaining": max(0, task.target_review_words - review_done),
            "due": _count(db, _review_queue_stmt(user, book)),
        },
        "mastered": mastered,
    }


def study_queue(
    db: Session,
    user: User,
    mode: str = "new",
    book: str | None = None,
    limit: int | None = None,
) -> dict:
    """取一批待学单词卡。默认按今日剩余目标决定数量。"""
    mode = mode if mode in STUDY_MODES else "new"
    task = get_or_create_daily_task(db, user)
    new_done, review_done = _study_counts(db, user.id, task.task_date)

    if mode == "new":
        remaining = max(0, task.target_new_words - new_done)
        stmt = _new_queue_stmt(user, book)
    else:
        remaining = max(0, task.target_review_words - review_done)
        stmt = _review_queue_stmt(user, book)

    take = max(1, min(limit, 100)) if limit else remaining
    words: list[Vocabulary] = []
    if take > 0:
        words = list(
            db.scalars(stmt.order_by(Vocabulary.order_index, Vocabulary.id).limit(take)).all()
        )

    states = _state_map(db, user.id, [w.id for w in words])
    return {
        "mode": mode,
        "book": book or "",
        "remaining": remaining,
        "items": [serialize_word(w, states.get(w.id)) for w in words],
    }


def apply_study_answer(
    db: Session,
    user: User,
    word: Vocabulary,
    action: str,
    mode: str | None = None,
    book_code: str = "",
) -> dict:
    """处理一次「没记住 / 记住了 / 已掌握」。

    - 已掌握：status=mastered，之后不再进任何队列
    - 记住了：进入复习阶段，按 REVIEW_STAGES 排下次复习日
    - 没记住：回到 learning，今天就能再复习
    """
    state = _get_or_create_state(db, user, word)
    if mode not in STUDY_MODES:
        mode = "review" if state.is_new_seen else "new"
    if action not in STUDY_ACTIONS:
        action = "remember"

    first_seen = not state.is_new_seen
    state.is_new_seen = True
    state.review_count = (state.review_count or 0) + 1
    state.exposure_count = (state.exposure_count or 0) + 1
    state.last_reviewed = _now()
    if book_code:
        state.book_code = book_code

    if action == "mastered":
        state.status = "mastered"
        state.mastery = 1.0
        state.review_stage = len(REVIEW_STAGES) - 1
        state.due_date = ""
    elif action == "remember":
        stage = min((state.review_stage or 0) + 1, len(REVIEW_STAGES) - 1)
        state.status = "review"
        state.review_stage = stage
        state.mastery = min(1.0, (state.mastery or 0) + 0.15)
        state.due_date = (date.today() + timedelta(days=REVIEW_STAGES[stage])).isoformat()
    else:
        state.status = "learning"
        state.review_stage = 0
        state.mastery = max(0.0, (state.mastery or 0) - 0.1)
        state.due_date = today_str()

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
            mode=mode,
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
            "mode": mode,
            "xp_gained": xp,
            "task": serialize_daily_task(task),
        }
    )
    return payload


def sync_study_progress(db: Session, user: User, task: DailyTask | None = None) -> DailyTask:
    """把今日新学/复习的进度同步到每日任务，并触发结算。

    done_words 取两者之和与既有值的较大者：收藏等旧路径也会写 done_words，
    用 max 避免把那些进度覆盖掉。
    """
    task = task or get_or_create_daily_task(db, user)
    new_done, review_done = _study_counts(db, user.id, task.task_date)
    task.done_new_words = new_done
    task.done_review_words = review_done
    task.done_words = max(task.done_words or 0, new_done + review_done)
    db.flush()
    settle_daily_task(db, task)
    db.flush()
    return task


LEADERBOARD_KINDS = ("xp", "streak", "contribution")


def leaderboard(db: Session, kind: str = "xp", limit: int = 50, me: User | None = None) -> dict:
    """三种榜单：经验值 / 连续打卡 / 贡献值。"""
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
