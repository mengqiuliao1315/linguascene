from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.data.wordbooks import BOOKS, WORDS
from app.models.learning import Vocabulary
from app.models.wordbook import Wordbook

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

BOOKS_BY_CODE: dict[str, dict] = {book["code"]: book for book in BOOKS}


def _upsert(db: Session, book_codes: set[str], position: int, item: dict) -> bool:
    word = db.scalar(select(Vocabulary).where(Vocabulary.word == item["word"]))
    created = word is None
    if word is None:
        word = Vocabulary(word=item["word"])
        db.add(word)

    word.books = ",".join(sorted(book_codes))

    word.phonetic_uk = item.get("uk", "")
    word.phonetic_us = item.get("us", "")
    word.phonetic = item.get("us") or item.get("uk") or word.phonetic or ""
    word.part_of_speech = item.get("pos", "")
    word.meaning = item.get("en", "")
    word.meaning_zh = item.get("zh", "")
    examples = item.get("ex") or []
    word.examples_json = json.dumps(examples, ensure_ascii=False)
    word.example = examples[0]["en"] if examples else ""
    word.tags = item.get("tags", "")
    word.unit = item.get("unit", "")
    word.order_index = position
    if book_codes:
        primary = sorted(book_codes)[0]
        word.level = BOOKS_BY_CODE.get(primary, {}).get("level", word.level or "B1")
    return created


def _json_sources() -> dict[str, list[dict]]:
    sources: dict[str, list[dict]] = {}
    for code in BOOKS_BY_CODE:
        path = DATA_DIR / f"{code}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("跳过无法解析的词表 %s：%s", path.name, exc)
            continue
        words = payload.get(code)
        if isinstance(words, list) and words:
            sources[code] = words
    return sources


def seed_wordbooks(db: Session | None = None) -> dict:
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        result = _seed_wordbooks_impl(db)
        if own_session:
            db.commit()
        return result
    finally:
        if own_session:
            db.close()


def _seed_wordbooks_impl(db: Session) -> dict:
    for index, book in enumerate(BOOKS):
        row = db.scalar(select(Wordbook).where(Wordbook.code == book["code"]))
        if row is None:
            row = Wordbook(code=book["code"])
            db.add(row)
        row.name = book["name"]
        row.name_zh = book["name_zh"]
        row.description = book["description"]
        row.icon = book["icon"]
        row.level = book["level"]
        row.order_index = book.get("order_index", index)
    db.flush()

    by_word: dict[str, dict] = {}

    def collect(code: str, items: list[dict]) -> None:
        for item in items:
            word = item["word"]
            entry = by_word.get(word)
            if entry is None:
                by_word[word] = {"item": dict(item), "books": {code}}
                continue
            entry["books"].add(code)
            has_new = bool(item.get("ex"))
            has_old = bool(entry["item"].get("ex"))
            if has_new or not has_old:
                entry["item"] = dict(item)

    for code, items in WORDS.items():
        collect(code, items)
    for code, items in _json_sources().items():
        collect(code, items)

    added = updated = 0
    for position, entry in enumerate(by_word.values()):
        if _upsert(db, entry["books"], position, entry["item"]):
            added += 1
        else:
            updated += 1
    db.flush()

    counts: dict[str, int] = {}
    for book in BOOKS:
        code = book["code"]
        total = int(
            db.scalar(
                select(func.count())
                .select_from(Vocabulary)
                .where(Vocabulary.books.like(f"%{code}%"))
            )
            or 0
        )
        row = db.scalar(select(Wordbook).where(Wordbook.code == code))
        if row is not None:
            row.word_count = total
        counts[code] = total

    db.flush()
    return {"added": added, "updated": updated, "counts": counts}
