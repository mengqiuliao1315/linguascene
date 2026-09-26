"""批量导入词表。

用法：
    python -m app.import_words words.json

JSON 格式（键是词书 code，值为单词对象数组）：

    {
      "cet4": [
        {
          "word": "abandon",
          "uk": "/əˈbændən/",
          "us": "/əˈbændən/",
          "pos": "v.",
          "zh": "抛弃；放弃",
          "en": "to leave someone or something",
          "ex": [{"en": "They abandoned the car.", "zh": "他们丢弃了那辆车。"}],
          "unit": "Unit 1",
          "tags": "core,verb"
        }
      ]
    }

词书 code 必须已在 app/data/wordbooks.py 的 BOOKS 里定义。
重复导入同一个单词会更新内容而不是新建，可以安全地反复执行。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.core.database import Base, SessionLocal, engine
from app.models.learning import Vocabulary
from app.models.wordbook import Wordbook
from app.services.wordbook_seed import BOOKS_BY_CODE


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("JSON 顶层必须是 {book_code: [单词, ...]} 形式")
    return data


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1

    path = Path(argv[1])
    if not path.exists():
        print(f"文件不存在：{path}")
        return 1

    payload = load(path)
    unknown = [code for code in payload if code not in BOOKS_BY_CODE]
    if unknown:
        print(f"未知词书 code：{', '.join(unknown)}")
        print(f"已定义的词书：{', '.join(sorted(BOOKS_BY_CODE))}")
        return 1

    import app.models  # noqa: F401  确保所有模型已注册

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    added = updated = 0
    try:
        for book_code, words in payload.items():
            level = BOOKS_BY_CODE[book_code]["level"]
            for position, item in enumerate(words):
                word = db.scalar(select(Vocabulary).where(Vocabulary.word == item["word"]))
                if word is None:
                    word = Vocabulary(word=item["word"])
                    db.add(word)
                    added += 1
                else:
                    updated += 1

                books = {b for b in (word.books or "").split(",") if b}
                books.add(book_code)
                word.books = ",".join(sorted(books))

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
                word.level = level
        db.flush()

        # 同步词书封面上的词数
        for book_code in payload:
            total = db.scalar(
                select(func.count())
                .select_from(Vocabulary)
                .where(Vocabulary.books.like(f"%{book_code}%"))
            )
            row = db.scalar(select(Wordbook).where(Wordbook.code == book_code))
            if row is not None:
                row.word_count = int(total or 0)

        db.commit()
    finally:
        db.close()

    print(f"导入完成：新增 {added} 个，更新 {updated} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
