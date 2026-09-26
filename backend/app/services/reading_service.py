"""精读服务：逐句讲解、笔记、公开分享。

设计要点：
- 平台文章与用户上传共用同一套精读流程，逐句结果按句索引缓存，
  同一篇材料第二次打开不再调用模型。
- 平台文章的内置讲解（app/data/reading_content.py）优先于缓存与模型：
  站内固定内容不配 Key、断网也要能精读。
- 笔记按 (文档, 用户) 归属。公开文章下每个读者写自己的一份，
  互不干扰。
"""

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

# 一次模型调用分析多少句的默认值。实际运行时由自适应器按限流/截断/超时
# 反馈升降（见 app.ai.batch_tuner），用户无需手填参数。
_DEFAULT_SENTENCE_BATCH_SIZE = 4

# 常见的缩写与称谓，切句时不当成句末
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e",
    "inc", "ltd", "co", "u.s", "u.k", "no", "fig", "al",
}

# 句末标点后面可以是空白、行尾，也可以紧跟一个大写字母。
# PDF 抽出来的文本常常丢句间空格（"work?Sometimes"、"task.Other times"），
# 只认「标点 + 空白」会把整段当成一句，讲解也就变成一大坨。
# 标点后收尾的引号/括号一并吃进这一句，句子的字符就不会被切走。
_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*(?=\s|$|[A-Z])")

# 含英文字母才算「要精读的句子」。
_HAS_ENGLISH = re.compile(r"[A-Za-z]")


def split_sentences(text: str) -> list[tuple[int, str]]:
    """把正文切成 (段落序号, 句子) 列表。

    只做保守的规则切分：句末标点后跟空白或大写字母（PDF 常丢句间空格），
    且不是常见缩写；不含英文字母的片段（中文标题、译文）直接丢掉。
    """
    result: list[tuple[int, str]] = []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    for p_index, paragraph in enumerate(paragraphs):
        # 段内单换行视为同一段的续行
        flat = re.sub(r"\s*\n\s*", " ", paragraph)
        # 按句末标点的位置切片，而不是 split：切点本身要留在句子里
        chunks: list[str] = []
        start = 0
        for match in _SENTENCE_END.finditer(flat):
            chunks.append(flat[start : match.end()])
            start = match.end()
        chunks.append(flat[start:])

        buffer = ""
        for chunk in chunks:
            # 句间空白不进句子，边界处收掉
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

    # 只留含英文字母的句子：上传材料里的中文标题、中文译文段落不该被当成
    # 待讲解的句子（中文由模型在 translation 里给，不必逐句解析）。
    return [item for item in result if _HAS_ENGLISH.search(item[1])]


def _ends_with_abbreviation(text: str) -> bool:
    match = re.search(r"([A-Za-z.]+)\.$", text)
    if not match:
        return False
    return match.group(1).rstrip(".").lower() in _ABBREVIATIONS


# --------------------------------------------------------------- 词形还原

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
    """给出词典形（原型）。

    英文的 -ed / -ing 还原在结构上有歧义：changed 的词干是 change，
    而 walked 的词干是 walk，仅看拼写无法区分。因此接受一个可选词表
    `known`：候选里第一个出现在词表中的即为答案。没有词表时按最可能
    的顺序退而求其次（best effort）。
    """
    raw = (word or "").strip()
    if not raw:
        return ""

    # 多词条目（如 artificial intelligence）不做词形还原：下面的正则会把
    # 空格一并删掉，把它拼成一个词 artificialintelligence。原样小写返回。
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
            candidates.append(cleaned[:-4])          # running -> run
        candidates.append(cleaned[:-3] + "e")        # making -> make
        candidates.append(cleaned[:-3])              # walking -> walk
    if len(cleaned) > 4 and cleaned.endswith("ed"):
        if cleaned[-3] == cleaned[-4] and cleaned[-3] not in "aeiou":
            candidates.append(cleaned[:-3])          # stopped -> stop
        candidates.append(cleaned[:-1])              # changed -> change
        candidates.append(cleaned[:-2])              # walked -> walk

    # 不再把 -ly 副词还原成形容词：significantly 的原型就是 significantly，
    # 砍成 significant 会得到"形容词 + 副词释义"的错误词条
    # （之前就出现过 "significant (significantly) 显著地"）。

    candidates = [c for c in candidates if len(c) >= 3]

    if known:
        for candidate in candidates:
            if candidate in known:
                return candidate

    return candidates[0] if candidates else cleaned


def _dictionary_words(db: Session) -> set[str]:
    """词典表 + 内置分级词表，用于校验词形还原结果。"""
    from app.ai.rule_engine import VOCAB_BY_LEVEL

    words = {w.lower() for w in db.execute(select(Vocabulary.word)).scalars().all()}
    for level_words in VOCAB_BY_LEVEL.values():
        words.update(level_words.keys())
    return words


def lemma_for(word: str, known: set[str] | None = None) -> str:
    """挑一个靠谱的原型。

    -ing / -ed 的还原有歧义：meeting 的原型到底是 meeting 还是 meet，
    光看拼写分不出来。所以先看这个词本身是不是词典条目——是的话它自己
    就是原型，没有理由再砍一刀；不是才退回词形还原。
    """
    raw = (word or "").strip()
    if not raw:
        return ""
    if re.search(r"\s", raw):
        return re.sub(r"\s+", " ", raw).lower()
    if known and raw.lower() in known:
        return raw.lower()
    return lemmatize(raw, known)


def _fallback_words(sentence: str, known: set[str], limit: int = 3) -> list[dict]:
    """离线词表没命中时，直接从句子里挑实词。

    保证「重点单词」不会空着。释义能查词典就查，查不到留空，
    不编造释义。
    """
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


# --------------------------------------------------------------- 文档读取


class DocumentNotFound(Exception):
    pass


class DocumentForbidden(Exception):
    pass


@dataclass
class Document:
    kind: str  # article | content
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
    """读取文档并做权限判断。

    平台文章人人可读；用户上传只有作者本人或已公布时才能读。
    """
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


# --------------------------------------------------------------- 逐句讲解


def builtin_sentences(document: Document) -> list[dict] | None:
    """平台文章的内置逐句讲解；这篇没有内置数据时返回 None。

    内置讲解随文章写在仓库里、人工校对过，也不依赖模型，所以它是
    「断网 / 没配 Key 也能精读」的兜底，调用方拿到就应落库复用。
    """
    return build_sentences(document.title, split_sentences(document.body))


def stored_sentences(document: Document) -> list[dict]:
    """文档里存着的逐句讲解。

    只有和当前切句结果对得上才可用：老库或旧切句逻辑留下的缓存（比如整段
    被当成一句）照用会把错的粒度一直显示、复用下去，这里当作没有，
    让调用方重新生成。
    """
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
    """不用跑模型就能拿到的逐句讲解：平台内置优先，其次文档缓存。

    平台文章自带讲解（重点单词/固定搭配/语法/翻译），优先级高于缓存：
    老库里可能存着模型早期的错误结果（比如把 artificial intelligence
    的词形还原成了 artificialintelligence），命中缓存就会一直错下去。
    内置讲解是人工校对过的，force 重新分析也用它，别让模型覆盖成更差的版本。
    """
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
    """把一句的模型/规则分析整理成前端直接可渲染的结构。"""
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
    """切批：第一句单独一批，其余按 batch_size 分。

    每次模型调用都有约 10s 的固定等待（实测）。整批等齐才发的话，最上面
    那句要陪着后面的句子一起等一二十秒；第一句先单独跑，用户几秒内就能读
    到它的讲解，剩下的句子照常批量并发。
    """
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
    """并发逐句分析，产出 (句子下标, 讲解, 是否来自模型)，并发跑、按句序出。

    模型调用是这里唯一的大头开销，且句子之间互不依赖。单句一次往返时一篇
    长文要排十几轮模型调用，逐句渐进返回虽好、全篇就绪仍要等几分钟。这里
    改成按批分析：一次调用塞若干句，往返次数按批数缩；批与批之间并发跑，
    首句就绪时间基本不变。

    但吐出的顺序必须按句序，不能按完成顺序：并发下第 5 句的批可能先跑完，
    直接发出去用户就会看到「下面那句先出」，读起来是跳的。所以完成的批先
    攒着，句序上的缺口一补上就整段发出去。

    没配模型时 SentenceAgent 内部走离线规则引擎，批量路径照样适用；模型
    调用失败或返回条数对不齐时 Agent 会自动降级成逐句兜底，不会整批空着。
    """
    if not segments:
        return

    # 批大小和并发度让系统自己摸：用户不知道自己模型的限流和延迟，
    # 自适应器按运行时反馈（截断/限流/超时/顺利）升降，跨请求记住。
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
        # chunk 与 batched 同长同序，按原句下标归位
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
        # 谁先跑完先攒着，不直接发：只有句序上连着的部分能往外吐，
        # 否则并发会把后面那句提前顶到用户眼前
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
    """逐句产出 (句子下标, 讲解, 是否来自模型)。批量和流式两条路都走它。"""
    for index, analysis, from_model in _iter_analyses(agent, segments, level, title):
        paragraph, text = segments[index]
        yield index, _sentence_payload(index, paragraph, text, analysis, known), from_model


def _persist_sentences(
    db: Session, document: Document, sentences: list[dict], model_hits: int
) -> None:
    """全句都来自离线兜底时说明模型这次没调通，绝不落库：

    否则一次超时就会被当成"这篇的讲解"长期复用，用户看到的是空翻译和空释义，
    还以为 AI 功能坏了。
    """
    if not sentences or not model_hits:
        return
    _store_sentences(db, document, json.dumps(sentences, ensure_ascii=False))


def analyze_document(
    db: Session,
    user: User,
    document: Document,
    force: bool = False,
    provider: AIProvider | None = None,
) -> dict:
    """逐句讲解。结果按句索引缓存进文档，二次打开直接复用。"""
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
    _persist_sentences(db, document, sentences, model_hits)
    return {
        "level": document.level,
        "sentences": sentences,
        "generated": bool(model_hits),
    }


def sse_event(event: str, data: dict) -> str:
    """拼一个 SSE 帧。

    `data` 必须是一行 JSON（json.dumps 不会产出裸换行），否则接收端会在
    半截处断开一帧，把后面的内容当成新字段。
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_analysis(
    db: Session,
    user: User,
    document: Document,
    *,
    force: bool = False,
    provider: AIProvider | None = None,
) -> Iterator[str]:
    """逐句讲解的渐进式返回，产出 SSE 帧。

    整篇一次性返回时，用户要对着空页面等到最后一句跑完（长文几十秒）。
    这里改成先发全部句子的骨架、再跑完一句发一句：前端收到第一帧就能把
    原文排出来，读到哪句哪句就绪，剩下的位置先占着。

    事件：start（骨架）→ sentence × N → done。出错发 error 事件而不抛异常——
    响应头早已发出，抛异常只会让连接断在半路，前端拿不到任何解释。
    """
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
            db, document, [by_index[i] for i in sorted(by_index)], model_hits
        )
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
    """把笔记挂到对应句子上，返回给前端渲染。"""
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
    """挑出要提建议的句子。下标留空表示整篇。"""
    wanted = set(sentence_indexes or [])
    return [item for item in sentences if not wanted or item["index"] in wanted]


def iter_suggestions(
    targets: list[dict],
    cefr_level: str,
    provider: AIProvider | None = None,
) -> Iterator[tuple[int, list[dict], bool]]:
    """逐句产出 (句子下标, 换算好区间的建议, 是否来自模型)，谁先跑完谁先出。

    模型调用是这里唯一的大头开销，句子之间互不依赖。串行会让长文卡在代理
    超时上，整批等齐再返回又让首句白等——所以并发跑、先完成的先吐，一次性
    接口和流式接口都走这一条路，避免两边各写一套挑选逻辑。
    """
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
    """标注建议的渐进式返回，产出 SSE 帧。

    整篇等齐再返回时，用户要对着「挑选中…」等所有句子都过一遍模型。这里改成
    跑完一句发一句：建议一到就先画在对应句子上，长文也能边看边挑。

    事件：start（总数）→ sentence × N → done。出错发 error 事件而不抛异常——
    响应头早已发出，抛异常只会让连接断在半路，前端拿不到任何解释。
    """
    try:
        sentences = analyze_document(db, user, document)["sentences"]
        # 逐句讲解是本次的副产品，先落库：客户端中断也别让这份缓存白跑
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
    """把 Agent 给的 span 换算成带字符区间的建议。

    模型只保证 `text` 能在句子里找到，字符区间在这里统一算，
    前端拿到的就是能直接对齐 [start, end) 的结构。
    """
    result: list[dict] = []
    lowered = sentence.lower()
    cursor = 0
    for span in spans:
        text = getattr(span, "text", "") or ""
        if not text:
            continue
        # 同一个词重复出现时，从上次结束的位置往后找，避免全指到第一处
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


# --------------------------------------------------------------- 笔记


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
    """找同一句里文本相同的词/搭配批注（不分大小写），用于挡住重复添加。"""
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
    # 单词没给原型就自己还原，保证入词库时用原型而不是屈折形式
    if kind == "word" and not lemma.strip():
        lemma = lemma_for(cleaned, _dictionary_words(db))

    # 同一句里同一个词/搭配只留一条，已经加过就原样返回旧的那条。
    # 前端芯片加完会变成 ✓ 挡住后续点击，但双击、多开标签页，或者「AI 建议标注」
    # 和手动添加撞在一起时，光靠前端状态挡不住，所以这里兜底。
    #
    # 只对没有字符区间的批注去重：同一个词在一句里出现两次时，字符区间是区分
    # 它们的唯一依据，按文本去重会把第二次误判成重复。自由笔记（note）不参与，
    # 它和词条是两回事，同一个锚点上允许同时存在。
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
    """用户词库里已有的词，用于在笔记上标记"已加入"。"""
    from app.models.learning import UserVocabulary

    rows = db.execute(
        select(Vocabulary.word)
        .join(UserVocabulary, UserVocabulary.vocabulary_id == Vocabulary.id)
        .where(UserVocabulary.user_id == user.id)
    ).scalars().all()
    return {w.lower() for w in rows}


# --------------------------------------------------------------- 材料库


def list_materials(db: Session, user: User, source: str = "all") -> list[dict]:
    """阅读库：平台材料 + 我的上传 + 他人公布。

    source: all | platform | mine | shared
    """
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
