import json
import logging
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from inspect import signature

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.agents import SentenceAgent
from app.ai.agents.annotation_agent import AnnotationAgent
from app.ai.batch_tuner import get_batch_tuner
from app.ai.provider import AIProvider
from app.data.reading_content import build_sentences
from app.models.content import Article, ArticleAnalysis, ReadingNote, UserContent
from app.models.learning import Vocabulary
from app.models.user import User

logger = logging.getLogger(__name__)

_DEFAULT_SENTENCE_BATCH_SIZE = 4

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e",
    "inc", "ltd", "co", "u.s", "u.k", "no", "fig", "al",
}

_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*(?=\s|$|[A-Z])")

_HAS_ENGLISH = re.compile(r"[A-Za-z]")


def split_sentences(text: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    for p_index, paragraph in enumerate(paragraphs):
        flat = re.sub(r"\s*\n\s*", " ", paragraph)
        chunks: list[str] = []
        start = 0
        for match in _SENTENCE_END.finditer(flat):
            chunks.append(flat[start : match.end()])
            start = match.end()
        chunks.append(flat[start:])

        buffer = ""
        for chunk in chunks:
            piece = chunk.strip()
            candidate = f"{buffer} {piece}" if buffer else piece
            if not candidate:
                continue
            if _ends_with_abbreviation(candidate):
                buffer = candidate
                continue
            result.append((p_index, candidate))
            buffer = ""

        if buffer:
            result.append((p_index, buffer))

    return [item for item in result if _HAS_ENGLISH.search(item[1])]


def _ends_with_abbreviation(text: str) -> bool:
    match = re.search(r"([A-Za-z.]+)\.$", text)
    if not match:
        return False
    return match.group(1).rstrip(".").lower() in _ABBREVIATIONS


IRREGULAR_LEMMAS = {
    "am": "be", "is": "be", "are": "be", "was": "be", "were": "be", "been": "be",
    "has": "have", "had": "have", "does": "do", "did": "do", "done": "do",
    "went": "go", "gone": "go", "made": "make", "took": "take", "taken": "take",
    "came": "come", "saw": "see", "seen": "see", "got": "get", "gotten": "get",
    "gave": "give", "given": "give", "found": "find", "thought": "think",
    "brought": "bring", "bought": "buy", "built": "build", "kept": "keep",
    "left": "leave", "led": "lead", "ran": "run", "said": "say", "told": "tell",
    "felt": "feel", "knew": "know", "known": "know", "grew": "grow", "grown": "grow",
    "children": "child", "people": "person", "men": "man", "women": "woman",
    "better": "good", "best": "good", "worse": "bad", "worst": "bad",
    "more": "much", "most": "much", "less": "little", "least": "little",
    "analyses": "analysis", "studies": "study", "companies": "company",
}


def lemmatize(word: str, known: set[str] | None = None) -> str:
    raw = (word or "").strip()
    if not raw:
        return ""

    if re.search(r"\s", raw):
        return re.sub(r"\s+", " ", raw).lower()

    cleaned = re.sub(r"[^A-Za-z'-]", "", raw).strip("'-").lower()
    if not cleaned:
        return raw.lower()

    if cleaned in IRREGULAR_LEMMAS:
        return IRREGULAR_LEMMAS[cleaned]

    candidates: list[str] = []

    if len(cleaned) > 4 and cleaned.endswith("ies"):
        candidates.append(cleaned[:-3] + "y")
    if len(cleaned) > 4 and cleaned.endswith("es"):
        candidates.append(cleaned[:-1])
        candidates.append(cleaned[:-2])
    if len(cleaned) > 3 and cleaned.endswith("s") and not cleaned.endswith("ss"):
        candidates.append(cleaned[:-1])
    if len(cleaned) > 5 and cleaned.endswith("ing"):
        if cleaned[-4] == cleaned[-5] and cleaned[-4] not in "aeiou":
            candidates.append(cleaned[:-4])
        candidates.append(cleaned[:-3] + "e")
        candidates.append(cleaned[:-3])
    if len(cleaned) > 4 and cleaned.endswith("ed"):
        if cleaned[-3] == cleaned[-4] and cleaned[-3] not in "aeiou":
            candidates.append(cleaned[:-3])
        candidates.append(cleaned[:-1])
        candidates.append(cleaned[:-2])


    candidates = [c for c in candidates if len(c) >= 3]

    if known:
        for candidate in candidates:
            if candidate in known:
                return candidate

    return candidates[0] if candidates else cleaned


def _dictionary_words(db: Session) -> set[str]:
    from app.ai.rule_engine import VOCAB_BY_LEVEL

    words = {w.lower() for w in db.execute(select(Vocabulary.word)).scalars().all()}
    for level_words in VOCAB_BY_LEVEL.values():
        words.update(level_words.keys())
    return words


def lemma_for(word: str, known: set[str] | None = None) -> str:
    raw = (word or "").strip()
    if not raw:
        return ""
    if re.search(r"\s", raw):
        return re.sub(r"\s+", " ", raw).lower()
    if known and raw.lower() in known:
        return raw.lower()
    return lemmatize(raw, known)


def _fallback_words(sentence: str, known: set[str], limit: int = 3) -> list[dict]:
    from app.ai.rule_engine import STOPWORDS

    picked: list[dict] = []
    seen: set[str] = set()

    for raw in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", sentence):
        lowered = raw.lower()
        if lowered in STOPWORDS or lowered in seen:
            continue
        if len(lowered) < 4:
            continue
        seen.add(lowered)
        lemma = lemma_for(lowered, known)
        picked.append({"word": lowered, "lemma": lemma, "meaning": ""})
        if len(picked) >= limit:
            break
    return picked


class DocumentNotFound(Exception):
    pass


class DocumentForbidden(Exception):
    pass


@dataclass
class Document:
    kind: str
    id: int
    title: str
    body: str
    level: str
    author_name: str
    is_public: bool
    is_mine: bool
    cached_sentences: str | None

    @property
    def ref(self) -> dict:
        return {"article_id": self.id} if self.kind == "article" else {"content_id": self.id}


def load_document(
    db: Session,
    user: User,
    *,
    article_id: int | None = None,
    content_id: int | None = None,
) -> Document:
    if article_id is not None:
        article = db.get(Article, article_id)
        if not article:
            raise DocumentNotFound("材料不存在")
        cached = article.analysis.sentences_json if article.analysis else None
        return Document(
            kind="article",
            id=article.id,
            title=article.title,
            body=article.content,
            level=article.level,
            author_name=article.source or "LinguaScene",
            is_public=True,
            is_mine=False,
            cached_sentences=cached,
        )

    if content_id is None:
        raise DocumentNotFound("缺少材料标识")

    content = db.get(UserContent, content_id)
    if not content:
        raise DocumentNotFound("材料不存在")

    is_mine = content.user_id == user.id
    if not is_mine and not content.is_public:
        raise DocumentForbidden("该材料未公布")

    return Document(
        kind="content",
        id=content.id,
        title=content.title,
        body=content.content,
        level=user.cefr_level,
        author_name=content.author_name or "匿名",
        is_public=bool(content.is_public),
        is_mine=is_mine,
        cached_sentences=content.sentences_json,
    )


def builtin_sentences(document: Document) -> list[dict] | None:
    return build_sentences(document.title, split_sentences(document.body))


def stored_sentences(document: Document) -> list[dict]:
    if not document.cached_sentences:
        return []
    try:
        cached = json.loads(document.cached_sentences)
    except ValueError:
        return []
    if not isinstance(cached, list):
        return []
    if len(cached) != len(split_sentences(document.body)):
        return []
    return cached


def _reusable_sentences(
    db: Session,
    document: Document,
    segments: list[tuple[int, str]],
    *,
    force: bool,
) -> list[dict] | None:
    builtin = build_sentences(document.title, segments)
    if builtin:
        blob = json.dumps(builtin, ensure_ascii=False)
        if document.cached_sentences != blob:
            _store_sentences(db, document, blob)
        return builtin

    if not force:
        cached = stored_sentences(document)
        if cached:
            return cached

    return None


def _sentence_payload(
    index: int,
    paragraph: int,
    text: str,
    analysis,
    known: set[str],
) -> dict:
    words = []
    for item in analysis.vocabulary:
        raw = item.word if hasattr(item, "word") else item.get("word", "")
        if not raw:
            continue
        lemma = lemma_for(raw, known)
        words.append(
            {
                "word": raw,
                "lemma": lemma,
                "meaning": item.meaning if hasattr(item, "meaning") else item.get("meaning", ""),
                "phonetic": getattr(item, "phonetic", "") or "",
                "part_of_speech": getattr(item, "part_of_speech", "") or "",
            }
        )

    if not words:
        words = _fallback_words(text, known)

    return {
        "index": index,
        "paragraph": paragraph,
        "text": text,
        "translation": analysis.chinese_meaning,
        "main_clause": analysis.main_clause,
        "words": words,
        "phrases": [
            {
                "phrase": p.phrase,
                "meaning": p.meaning,
                "example": p.example,
            }
            for p in analysis.collocations
        ],
        "grammar": [
            {
                "point": g.point,
                "explanation": g.explanation,
                "example": g.example,
            }
            for g in analysis.grammar_points
        ],
        "explanation": analysis.natural_alternative,
    }


def _chunk_indexes(total: int, batch_size: int) -> list[list[int]]:
    if total == 0:
        return []
    if total == 1:
        return [[0]]
    chunks: list[list[int]] = [[0]]
    for start in range(1, total, batch_size):
        chunks.append(list(range(start, min(start + batch_size, total))))
    return chunks


def _iter_analyses(
    agent: SentenceAgent,
    segments: list[tuple[int, str]],
    level: str,
    title: str,
) -> Iterator[tuple[int, object, bool]]:
    if not segments:
        return

    batch_size, workers = get_batch_tuner().current()

    chunks: list[list[int]] = _chunk_indexes(len(segments), batch_size)

    def run(chunk: list[int]) -> list[tuple[int, object, bool]]:
        texts = [segments[i][1] for i in chunk]
        if chunk == [0] and "fast" in signature(
            agent.analyze_batch_with_status
        ).parameters:
            batched = agent.analyze_batch_with_status(
                texts, level, context=title, fast=True
            )
        else:
            batched = agent.analyze_batch_with_status(texts, level, context=title)
        return [
            (chunk[pos], analysis, from_model)
            for pos, (analysis, from_model) in enumerate(batched)
        ]

    workers = min(workers, len(chunks))
    if workers == 1:
        yield from run(chunks[0])
        return

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, chunk) for chunk in chunks]
        done: dict[int, tuple[int, object, bool]] = {}
        nxt = 0
        for future in as_completed(futures):
            for item in future.result():
                done[item[0]] = item
            while nxt in done:
                yield done.pop(nxt)
                nxt += 1


def _iter_sentence_payloads(
    agent: SentenceAgent,
    segments: list[tuple[int, str]],
    level: str,
    title: str,
    known: set[str],
) -> Iterator[tuple[int, dict, bool]]:
    for index, analysis, from_model in _iter_analyses(agent, segments, level, title):
        paragraph, text = segments[index]
        yield index, _sentence_payload(index, paragraph, text, analysis, known), from_model


def _persist_sentences(
    db: Session,
    document: Document,
    sentences: list[dict],
    model_hits: int,
    *,
    segments: list[tuple[int, str]],
    provider: AIProvider | None,
) -> None:
    if not sentences or len(sentences) != len(segments):
        return
    if not model_hits and not (provider is None or provider.is_mock):
        return
    _store_sentences(db, document, json.dumps(sentences, ensure_ascii=False))


def analyze_document(
    db: Session,
    user: User,
    document: Document,
    force: bool = False,
    provider: AIProvider | None = None,
) -> dict:
    segments = split_sentences(document.body)

    ready = _reusable_sentences(db, document, segments, force=force)
    if ready is not None:
        return {"level": document.level, "sentences": ready, "generated": True}

    agent = SentenceAgent(provider)
    known = _dictionary_words(db)

    by_index: dict[int, dict] = {}
    model_hits = 0
    for index, payload, from_model in _iter_sentence_payloads(
        agent, segments, document.level, document.title, known
    ):
        model_hits += 1 if from_model else 0
        by_index[index] = payload

    sentences = [by_index[i] for i in sorted(by_index)]
    _persist_sentences(
        db,
        document,
        sentences,
        model_hits,
        segments=segments,
        provider=provider,
    )
    return {
        "level": document.level,
        "sentences": sentences,
        "generated": bool(model_hits),
    }


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_analysis(
    db: Session,
    user: User,
    document: Document,
    *,
    force: bool = False,
    provider: AIProvider | None = None,
) -> Iterator[str]:
    segments = split_sentences(document.body)
    yield sse_event(
        "start",
        {
            "level": document.level,
            "total": len(segments),
            "sentences": [
                {"index": index, "paragraph": paragraph, "text": text}
                for index, (paragraph, text) in enumerate(segments)
            ],
        },
    )

    try:
        ready = _reusable_sentences(db, document, segments, force=force)
        if ready is not None:
            for item in ready:
                yield sse_event("sentence", {"sentence": {**item, "notes": []}})
            yield sse_event("done", {"generated": True})
            return

        agent = SentenceAgent(provider)
        known = _dictionary_words(db)

        by_index: dict[int, dict] = {}
        model_hits = 0
        for index, payload, from_model in _iter_sentence_payloads(
            agent, segments, document.level, document.title, known
        ):
            model_hits += 1 if from_model else 0
            by_index[index] = payload
            yield sse_event("sentence", {"sentence": {**payload, "notes": []}})

        _persist_sentences(
            db,
            document,
            [by_index[i] for i in sorted(by_index)],
            model_hits,
            segments=segments,
            provider=provider,
        )
        db.commit()
        yield sse_event("done", {"generated": bool(model_hits)})
    except Exception as exc:  # noqa: BLE001 - 流已开始，只能把错误当事件发出去
        logger.exception("逐句讲解流式生成失败")
        yield sse_event("error", {"detail": f"生成失败：{exc}"})


def _store_sentences(db: Session, document: Document, blob: str) -> None:
    if document.kind == "content":
        content = db.get(UserContent, document.id)
        if content:
            content.sentences_json = blob
    else:
        article = db.get(Article, document.id)
        if article:
            if article.analysis is None:
                article.analysis = ArticleAnalysis(article_id=article.id, level=article.level)
                db.add(article.analysis)
                db.flush()
            article.analysis.sentences_json = blob
    db.flush()


def build_annotations(sentences: list[dict], notes: list[ReadingNote]) -> list[dict]:
    by_sentence: dict[int, list[dict]] = {}
    for note in notes:
        by_sentence.setdefault(note.sentence_index, []).append(note_payload(note))
    return [
        {**sentence, "notes": by_sentence.get(sentence["index"], [])}
        for sentence in sentences
    ]


def suggestion_targets(
    sentences: list[dict], sentence_indexes: list[int] | None = None
) -> list[dict]:
    wanted = set(sentence_indexes or [])
    return [item for item in sentences if not wanted or item["index"] in wanted]


def iter_suggestions(
    targets: list[dict],
    cefr_level: str,
    provider: AIProvider | None = None,
) -> Iterator[tuple[int, list[dict], bool]]:
    if not targets:
        return

    agent = AnnotationAgent(provider)

    def run(item: dict) -> tuple[int, list[dict], bool]:
        suggestion, from_model = agent.suggest_with_status(item["text"], cefr_level)
        return (
            item["index"],
            build_suggestions(item["text"], suggestion.spans),
            from_model,
        )

    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        futures = [pool.submit(run, item) for item in targets]
        for future in as_completed(futures):
            yield future.result()


def stream_suggestions(
    db: Session,
    user: User,
    document: Document,
    *,
    provider: AIProvider | None = None,
    sentence_indexes: list[int] | None = None,
) -> Iterator[str]:
    try:
        sentences = analyze_document(db, user, document, provider=provider)["sentences"]
        db.commit()
    except Exception as exc:  # noqa: BLE001 - 流已开始，只能把错误当事件发出去
        logger.exception("标注建议流式生成失败")
        yield sse_event("error", {"detail": f"生成失败：{exc}"})
        return

    targets = suggestion_targets(sentences, sentence_indexes)
    yield sse_event("start", {"total": len(targets)})

    model_hits = 0
    try:
        for index, spans, from_model in iter_suggestions(
            targets, user.cefr_level, provider
        ):
            model_hits += 1 if from_model else 0
            yield sse_event("sentence", {"index": index, "spans": spans})
        yield sse_event(
            "done",
            {
                "generated": model_hits == len(targets)
                and not (provider.is_mock if provider is not None else False),
                "fallback_count": len(targets) - model_hits,
                "sentence_count": len(targets),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("标注建议流式生成失败")
        yield sse_event("error", {"detail": f"生成失败：{exc}"})


def build_suggestions(sentence: str, spans: list) -> list[dict]:
    result: list[dict] = []
    lowered = sentence.lower()
    cursor = 0
    for span in spans:
        text = getattr(span, "text", "") or ""
        if not text:
            continue
        index = lowered.find(text.lower(), cursor)
        if index < 0:
            index = lowered.find(text.lower())
        if index < 0:
            continue
        cursor = index + len(text)
        result.append(
            {
                "text": sentence[index : index + len(text)],
                "color": getattr(span, "color", "blue") or "blue",
                "reason": getattr(span, "reason", "") or "",
                "start_offset": index,
                "end_offset": index + len(text),
            }
        )
    return result


def note_payload(note: ReadingNote, in_vocabulary: bool = False) -> dict:
    return {
        "id": note.id,
        "sentence_index": note.sentence_index,
        "kind": note.kind,
        "text": note.text,
        "lemma": note.lemma or "",
        "meaning": note.meaning,
        "note": note.note,
        "color": note.color,
        "start_offset": note.start_offset,
        "end_offset": note.end_offset,
        "created_at": note.created_at,
        "in_vocabulary": in_vocabulary,
    }


def list_notes(db: Session, user: User, document: Document) -> list[ReadingNote]:
    query = select(ReadingNote).where(ReadingNote.user_id == user.id)
    query = _scope_notes(query, document)
    return list(db.execute(query.order_by(ReadingNote.sentence_index, ReadingNote.id)).scalars().all())


def _scope_notes(query, document: Document):
    if document.kind == "article":
        return query.where(ReadingNote.article_id == document.id)
    return query.where(ReadingNote.content_id == document.id)


def find_duplicate_note(
    db: Session,
    user: User,
    document: Document,
    sentence_index: int,
    text: str,
) -> ReadingNote | None:
    conditions = [
        ReadingNote.user_id == user.id,
        ReadingNote.sentence_index == sentence_index,
        ReadingNote.kind.in_(("word", "phrase")),
        func.lower(ReadingNote.text) == text.lower(),
    ]
    if document.kind == "article":
        conditions.append(ReadingNote.article_id == document.id)
    else:
        conditions.append(ReadingNote.content_id == document.id)
    return db.execute(select(ReadingNote).where(*conditions)).scalars().first()


def create_note(
    db: Session,
    user: User,
    document: Document,
    *,
    sentence_index: int,
    kind: str,
    text: str,
    lemma: str = "",
    meaning: str = "",
    note: str = "",
    color: str = "blue",
    start_offset: int = 0,
    end_offset: int = 0,
) -> ReadingNote:
    cleaned = text.strip()
    if kind == "word" and not lemma.strip():
        lemma = lemma_for(cleaned, _dictionary_words(db))

    if kind in ("word", "phrase") and start_offset == 0 and end_offset == 0:
        existing = find_duplicate_note(db, user, document, sentence_index, cleaned)
        if existing is not None:
            return existing

    row = ReadingNote(
        user_id=user.id,
        sentence_index=sentence_index,
        kind=kind,
        text=cleaned,
        lemma=lemma.strip(),
        meaning=meaning,
        note=note,
        color=color,
        start_offset=start_offset,
        end_offset=end_offset,
        article_id=document.id if document.kind == "article" else None,
        content_id=document.id if document.kind == "content" else None,
    )
    db.add(row)
    db.flush()
    return row


def get_note(db: Session, user: User, note_id: int) -> ReadingNote | None:
    return db.execute(
        select(ReadingNote).where(ReadingNote.id == note_id, ReadingNote.user_id == user.id)
    ).scalar_one_or_none()


def delete_note(db: Session, note: ReadingNote) -> None:
    db.delete(note)
    db.flush()


def vocabulary_word_set(db: Session, user: User) -> set[str]:
    from app.models.learning import UserVocabulary

    rows = db.execute(
        select(Vocabulary.word)
        .join(UserVocabulary, UserVocabulary.vocabulary_id == Vocabulary.id)
        .where(UserVocabulary.user_id == user.id)
    ).scalars().all()
    return {w.lower() for w in rows}


def list_materials(db: Session, user: User, source: str = "all") -> list[dict]:
    items: list[dict] = []

    if source in ("all", "platform"):
        articles = db.execute(
            select(Article).order_by(Article.published_at.desc())
        ).scalars().all()
        for article in articles:
            items.append(
                {
                    "id": article.id,
                    "title": article.title,
                    "source": "platform",
                    "author_name": article.source or "LinguaScene",
                    "content_type": "article",
                    "level": article.level,
                    "word_count": article.word_count or len(article.content.split()),
                    "read_minutes": article.read_minutes,
                    "is_public": True,
                    "is_mine": False,
                    "note_count": 0,
                    "created_at": article.published_at,
                }
            )

    if source in ("all", "mine"):
        mine = db.execute(
            select(UserContent)
            .where(UserContent.user_id == user.id)
            .order_by(UserContent.created_at.desc())
        ).scalars().all()
        for content in mine:
            items.append(_content_item(db, content, source="mine", is_mine=True))

    if source in ("all", "shared"):
        shared = db.execute(
            select(UserContent)
            .where(UserContent.is_public.is_(True), UserContent.user_id != user.id)
            .order_by(UserContent.created_at.desc())
        ).scalars().all()
        for content in shared:
            items.append(_content_item(db, content, source="shared", is_mine=False))

    return items


def _content_item(db: Session, content: UserContent, *, source: str, is_mine: bool) -> dict:
    note_count = db.execute(
        select(func.count(ReadingNote.id)).where(
            ReadingNote.content_id == content.id, ReadingNote.user_id == content.user_id
        )
    ).scalar_one()
    return {
        "id": content.id,
        "title": content.title,
        "source": source,
        "author_name": content.author_name or "匿名",
        "content_type": content.content_type,
        "level": "B1",
        "word_count": len(content.content.split()),
        "read_minutes": max(1, len(content.content.split()) // 200),
        "is_public": bool(content.is_public),
        "is_mine": is_mine,
        "note_count": note_count,
        "created_at": content.created_at,
    }


def set_public(
    db: Session, user: User, content_id: int, is_public: bool, author_name: str = ""
) -> UserContent:
    content = db.execute(
        select(UserContent).where(
            UserContent.id == content_id, UserContent.user_id == user.id
        )
    ).scalar_one_or_none()
    if not content:
        raise DocumentNotFound("材料不存在")

    content.is_public = 1 if is_public else 0
    if is_public and not content.author_name:
        content.author_name = author_name or user.username
    db.flush()
    return content


def delete_content(db: Session, user: User, content_id: int) -> None:
    content = db.execute(
        select(UserContent).where(
            UserContent.id == content_id, UserContent.user_id == user.id
        )
    ).scalar_one_or_none()
    if not content:
        raise DocumentNotFound("材料不存在")
    db.delete(content)
    db.flush()
