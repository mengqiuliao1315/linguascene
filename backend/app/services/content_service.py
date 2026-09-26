import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents import (
    ArticleAgent,
    SentenceAgent,
    TranslationAgent,
    VocabularyAgent,
    WordPhraseAgent,
)
from app.ai.provider import AIProvider
from app.core.storage import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    get_storage,
)
from app.models.content import Article, ArticleAnalysis, UserContent
from app.models.learning import Vocabulary
from app.models.user import User


def list_articles(
    db: Session, category: str | None = None, level: str | None = None
) -> list[Article]:
    query = select(Article).order_by(Article.published_at.desc())
    if category:
        query = query.where(Article.category == category)
    if level:
        query = query.where(Article.level == level)
    return list(db.execute(query).scalars().all())


def get_article(db: Session, article_id: int) -> Article | None:
    return db.execute(select(Article).where(Article.id == article_id)).scalar_one_or_none()


def analyze_article(
    db: Session, article: Article, cefr_level: str, provider: AIProvider | None = None
) -> ArticleAnalysis:
    if article.analysis:
        return article.analysis

    result = ArticleAgent(provider).analyze(
        article.content, cefr_level, cache_token=f"article-{article.id}"
    )

    analysis = ArticleAnalysis(
        article_id=article.id,
        summary=result.summary,
        level=result.level,
        keywords_json=json.dumps(
            [k.model_dump() for k in result.keywords], ensure_ascii=False
        ),
        phrases_json=json.dumps([p.model_dump() for p in result.phrases], ensure_ascii=False),
        grammar_json=json.dumps(
            [g.model_dump() for g in result.grammar_points], ensure_ascii=False
        ),
        questions_json=json.dumps(result.reading_questions, ensure_ascii=False),
        speaking_json=json.dumps(result.speaking_questions, ensure_ascii=False),
        writing_task=result.writing_task,
    )
    db.add(analysis)
    db.flush()
    return analysis


def analysis_payload(analysis: ArticleAnalysis) -> dict:
    return {
        "summary": analysis.summary,
        "level": analysis.level,
        "keywords": json.loads(analysis.keywords_json or "[]"),
        "phrases": json.loads(analysis.phrases_json or "[]"),
        "grammar_points": json.loads(analysis.grammar_json or "[]"),
        "reading_questions": json.loads(analysis.questions_json or "[]"),
        "speaking_questions": json.loads(analysis.speaking_json or "[]"),
        "writing_task": analysis.writing_task,
    }


def _dictionary_examples(entry: Vocabulary) -> list[str]:
    examples = [entry.example] if entry.example else []
    if examples or not entry.examples_json:
        return examples[:2]
    try:
        parsed = json.loads(entry.examples_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    for item in parsed:
        if isinstance(item, str) and item.strip():
            examples.append(item.strip())
        elif isinstance(item, dict):
            text = str(item.get("en") or item.get("sentence") or "").strip()
            if text:
                examples.append(text)
        if len(examples) >= 2:
            break
    return examples


def explain_word(
    word: str,
    context: str,
    cefr_level: str,
    db: Session | None = None,
    provider: AIProvider | None = None,
) -> dict:
    if db is not None:
        from app.services.reading_service import lemmatize

        cleaned = word.strip().lower()
        candidates = [cleaned]
        lemma = lemmatize(cleaned)
        if lemma and lemma != cleaned:
            candidates.append(lemma)
        entry = db.execute(
            select(Vocabulary).where(Vocabulary.word.in_(candidates))
        ).scalars().first()
        gloss = ""
        if entry is not None:
            gloss = (entry.meaning_zh or "").strip() or (entry.meaning or "").strip()
        if gloss:
            meanings = [
                part.strip()
                for part in gloss.replace("；", ";").split(";")
                if part.strip()
            ]
            return {
                "word": entry.word,
                "pronunciation": entry.phonetic_us or entry.phonetic or "",
                "part_of_speech": entry.part_of_speech or "",
                "core_meanings": meanings,
                "meaning_in_context": "",
                "collocations": [],
                "example_sentences": _dictionary_examples(entry),
                "related_words": [],
                "cefr_level": entry.level or cefr_level,
            }

    explanation = VocabularyAgent(provider).explain(word, context, cefr_level)
    return explanation.model_dump()


def analyze_sentence(
    sentence: str,
    cefr_level: str,
    context: str = "",
    provider: AIProvider | None = None,
) -> dict:
    return SentenceAgent(provider).analyze(sentence, cefr_level, context).model_dump()


def translate_text(text: str, provider: AIProvider | None = None) -> str:
    return TranslationAgent(provider).translate(text)


def analyze_selection(
    text: str,
    sentence: str,
    cefr_level: str,
    provider: AIProvider | None = None,
) -> tuple[dict, bool]:
    analysis, from_model = WordPhraseAgent(provider).analyze_with_status(
        text, sentence, cefr_level
    )
    return analysis.model_dump(), from_model


def _extract_text(filename: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(raw)
    if suffix == ".docx":
        return _extract_docx(raw)
    return raw.decode("utf-8", errors="ignore")


_HAS_ENGLISH = re.compile(r"[A-Za-z]")


def english_only(text: str) -> str:
    lines = [line for line in text.splitlines() if _HAS_ENGLISH.search(line)]
    return "\n".join(lines).strip()


def _extract_pdf(raw: bytes) -> str:
    import io

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:  # noqa: BLE001 - 解析失败时返回空，由上层标记 failed
        return ""


def _extract_docx(raw: bytes) -> str:
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        text = re.sub(r"<w:p[^>]*>", "\n", xml)
        text = re.sub(r"<[^>]+>", "", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    except Exception:  # noqa: BLE001
        return ""


def create_user_content(
    db: Session,
    user: User,
    *,
    title: str,
    filename: str = "",
    raw: bytes | None = None,
    text: str = "",
) -> UserContent:
    body = text.strip()
    if body:
        if len(body.encode("utf-8")) > MAX_UPLOAD_BYTES:
            raise ValueError("文本超过 10MB 限制")
        suffix = ".txt"
        key = ""
    else:
        if raw is None or not filename:
            raise ValueError("请上传文件或输入文本")
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(f"不支持的文件类型：{suffix}")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError("文件超过 10MB 限制")
        key = get_storage().save(filename, raw)
        body = _extract_text(filename, raw).strip()
        if not body:
            raise ValueError("无法从该文件中提取文本内容")

    body = english_only(body)
    if not body:
        raise ValueError("没有检测到英文正文，精读只解析英文文章")

    content = UserContent(
        user_id=user.id,
        title=title or (Path(filename).stem if filename else "未命名材料"),
        file_url=key,
        content=body[:100000],
        content_type=suffix.lstrip("."),
        status="ready",
    )
    db.add(content)
    db.flush()
    return content


def list_user_content(db: Session, user: User) -> list[UserContent]:
    return list(
        db.execute(
            select(UserContent)
            .where(UserContent.user_id == user.id)
            .order_by(UserContent.created_at.desc())
        ).scalars().all()
    )


def get_user_content(db: Session, user: User, content_id: int) -> UserContent | None:
    return db.execute(
        select(UserContent).where(
            UserContent.id == content_id, UserContent.user_id == user.id
        )
    ).scalar_one_or_none()


def generate_learning_material(
    db: Session,
    user: User,
    content: UserContent,
    force: bool = False,
    provider: AIProvider | None = None,
) -> dict:
    if content.analysis_json and not force:
        return json.loads(content.analysis_json)

    result = ArticleAgent(provider).analyze(
        content.content, user.cefr_level, cache_token=f"user-content-{content.id}"
    )
    payload = result.model_dump()
    content.analysis_json = json.dumps(payload, ensure_ascii=False)
    db.flush()
    return payload


def content_payload(content: UserContent) -> dict:
    return {
        "id": content.id,
        "title": content.title,
        "content_type": content.content_type,
        "status": content.status,
        "created_at": content.created_at,
        "word_count": len(content.content.split()),
        "preview": content.content[:160],
    }
