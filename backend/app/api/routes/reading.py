import json
import logging
from collections.abc import Iterator

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_user_provider
from app.core.database import SessionLocal, get_db
from app.core.storage import MAX_UPLOAD_BYTES
from app.core.uploads import read_limited
from app.models.content import UserContent
from app.models.user import User
from app.schemas.reading import (
    MaterialDetailOut,
    MaterialOut,
    NoteCreate,
    NoteOut,
    NoteUpdate,
    ReadingAnalysisOut,
    SelectionAnalyzeRequest,
    SelectionAnalysisOut,
    SuggestOut,
    SuggestRequest,
    SuggestedSpanOut,
)
from app.services import (
    content_service,
    pdf_service,
    reading_service,
    vocabulary_service,
    wordbook_service,
)

router = APIRouter(prefix="/api/reading", tags=["reading"])

logger = logging.getLogger(__name__)

_KINDS = ("article", "content")


def _resolve_document(
    db: Session, user: User, kind: str, material_id: int
) -> reading_service.Document:
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail="材料类型不存在")
    try:
        return reading_service.load_document(
            db,
            user,
            article_id=material_id if kind == "article" else None,
            content_id=material_id if kind == "content" else None,
        )
    except reading_service.DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except reading_service.DocumentForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _material_base(
    db: Session, user: User, document: reading_service.Document, note_count: int
) -> dict:
    word_count = len(document.body.split())
    return {
        "id": document.id,
        "title": document.title,
        "source": (
            "platform"
            if document.kind == "article"
            else ("mine" if document.is_mine else "shared")
        ),
        "author_name": document.author_name,
        "content_type": "article" if document.kind == "article" else "text",
        "level": document.level,
        "word_count": word_count,
        "read_minutes": max(1, word_count // 200),
        "is_public": document.is_public,
        "is_mine": document.is_mine,
        "note_count": note_count,
        "created_at": None,
    }


@router.get("/materials", response_model=list[MaterialOut])
def list_materials(
    source: str = "all",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MaterialOut]:
    if source not in ("all", "platform", "mine", "shared"):
        raise HTTPException(status_code=400, detail="source 取值不合法")
    return [
        MaterialOut.model_validate(row)
        for row in reading_service.list_materials(db, user, source)
    ]


@router.post("/materials/upload", response_model=MaterialDetailOut, status_code=201)
async def upload_material(
    file: UploadFile | None = File(default=None),
    text: str = Form(default=""),
    title: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialDetailOut:
    raw = await read_limited(file, MAX_UPLOAD_BYTES, too_large="文件超过 10MB 限制")
    try:
        content = content_service.create_user_content(
            db,
            user,
            title=title,
            filename=file.filename if file is not None else "",
            raw=raw,
            text=text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content.author_name = user.username
    wordbook_service.award_publish_once(
        db,
        user,
        content_id=content.id,
        amount=wordbook_service.CONTRIBUTION_RULES["publish_content"],
        reason="publish_content",
    )
    wordbook_service.record_reading(db, user, kind="content", material_id=content.id)
    db.commit()

    document = reading_service.load_document(db, user, content_id=content.id)
    return MaterialDetailOut(
        **_material_base(db, user, document, 0),
        content=document.body,
        sentences=[],
    )


@router.delete("/materials/content/{material_id}", status_code=204)
def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        reading_service.delete_content(db, user, material_id)
    except reading_service.DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()


@router.get("/materials/{kind}/{material_id}", response_model=MaterialDetailOut)
def get_material(
    kind: str,
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialDetailOut:
    document = _resolve_document(db, user, kind, material_id)

    sentences: list[dict] = reading_service.stored_sentences(document)

    if not sentences:
        builtin = reading_service.builtin_sentences(document)
        if builtin:
            sentences = builtin
            reading_service._store_sentences(
                db, document, json.dumps(builtin, ensure_ascii=False)
            )

    notes = reading_service.list_notes(db, user, document)
    known = reading_service.vocabulary_word_set(db, user)
    hidden = reading_service.hidden_sentence_indexes(db, user, document)
    annotated = reading_service.visible_sentences(
        reading_service.build_annotations(sentences, notes), hidden
    )
    for sentence in annotated:
        for note in sentence["notes"]:
            note["in_vocabulary"] = note["text"].lower() in known

    wordbook_service.record_reading(db, user, kind=kind, material_id=material_id)
    db.commit()

    return MaterialDetailOut(
        **_material_base(db, user, document, len(notes)),
        content=document.body,
        sentences=annotated,
    )


@router.post(
    "/materials/{kind}/{material_id}/sentences/{sentence_index}/hide",
    status_code=204,
)
def hide_material_sentence(
    kind: str,
    material_id: int,
    sentence_index: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除单句：只对自己生效，之后详情、分析与导出 PDF 都不再包含这句。"""
    document = _resolve_document(db, user, kind, material_id)
    reading_service.hide_sentence(db, user, document, sentence_index)
    db.commit()


@router.delete(
    "/materials/{kind}/{material_id}/sentences/{sentence_index}/hide",
    status_code=204,
)
def unhide_material_sentence(
    kind: str,
    material_id: int,
    sentence_index: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """撤销删除：把这一句恢复回来（前端只在当前页面会话内提供该入口）。"""
    document = _resolve_document(db, user, kind, material_id)
    reading_service.unhide_sentence(db, user, document, sentence_index)
    db.commit()


@router.post("/materials/{kind}/{material_id}/analyze", response_model=ReadingAnalysisOut)
def analyze_material(
    kind: str,
    material_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> ReadingAnalysisOut:
    document = _resolve_document(db, user, kind, material_id)
    payload = reading_service.analyze_document(
        db, user, document, force=force, provider=provider
    )
    hidden = reading_service.hidden_sentence_indexes(db, user, document)
    payload["sentences"] = reading_service.visible_sentences(
        payload["sentences"], hidden
    )
    db.commit()
    return ReadingAnalysisOut.model_validate(payload)


def _analysis_events(
    user_id: int,
    kind: str,
    material_id: int,
    force: bool,
    provider,
) -> Iterator[str]:
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            yield reading_service.sse_event("error", {"detail": "登录状态已失效，请重新登录"})
            return

        try:
            document = _resolve_document(db, user, kind, material_id)
        except HTTPException as exc:
            yield reading_service.sse_event("error", {"detail": exc.detail})
            return

        yield from reading_service.stream_analysis(
            db,
            user,
            document,
            force=force,
            provider=provider,
            hidden=reading_service.hidden_sentence_indexes(db, user, document),
        )
        db.commit()
    except Exception:  # noqa: BLE001 - 流已开始，异常只能记日志后断开
        logger.exception("逐句讲解流式响应异常")
        db.rollback()
    finally:
        db.close()


@router.get("/materials/{kind}/{material_id}/analyze/stream")
def analyze_stream(
    kind: str,
    material_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> StreamingResponse:
    """逐句讲解的渐进式返回（SSE）。

    整篇跑完再返回时，用户要对着空页面等几十秒。这里改成跑完一句发一句，
    前端收到骨架就能把原文排出来，读到哪句哪句就绪。

    用 GET 是为了让浏览器原生 EventSource 也能接；前端实际走 fetch 流式读取，
    因为 EventSource 没法带 Authorization 头。
    """
    _resolve_document(db, user, kind, material_id)

    return StreamingResponse(
        _analysis_events(user.id, kind, material_id, force, provider),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/materials/content/{material_id}/publish", response_model=MaterialOut)
def publish_material(
    material_id: int,
    is_public: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialOut:
    try:
        content = reading_service.set_public(
            db, user, material_id, is_public, user.username
        )
    except reading_service.DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if is_public:
        wordbook_service.award_publish_once(
            db,
            user,
            content_id=content.id,
            amount=wordbook_service.CONTRIBUTION_RULES["publish_content"],
            reason="publish_content",
        )
    db.commit()

    return MaterialOut.model_validate(
        reading_service._content_item(db, content, source="mine", is_mine=True)
    )


def _note_out(note, known: set[str]) -> NoteOut:
    return NoteOut.model_validate(
        reading_service.note_payload(note, note.text.lower() in known)
    )


@router.get("/materials/{kind}/{material_id}/notes", response_model=list[NoteOut])
def list_notes(
    kind: str,
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NoteOut]:
    document = _resolve_document(db, user, kind, material_id)
    notes = reading_service.list_notes(db, user, document)
    known = reading_service.vocabulary_word_set(db, user)
    return [_note_out(note, known) for note in notes]


@router.post(
    "/materials/{kind}/{material_id}/notes", response_model=NoteOut, status_code=201
)
def create_note(
    kind: str,
    material_id: int,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteOut:
    document = _resolve_document(db, user, kind, material_id)
    note = reading_service.create_note(
        db,
        user,
        document,
        sentence_index=payload.sentence_index,
        kind=payload.kind,
        text=payload.text,
        lemma=payload.lemma,
        meaning=payload.meaning,
        note=payload.note,
        color=payload.color,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
    )
    db.commit()
    return _note_out(note, reading_service.vocabulary_word_set(db, user))


def _collect_suggestions(
    db: Session,
    user: User,
    kind: str,
    material_id: int,
    payload: SuggestRequest,
    provider,
) -> SuggestOut:
    document = _resolve_document(db, user, kind, material_id)
    sentences = reading_service.analyze_document(
        db, user, document, provider=provider
    )["sentences"]
    db.commit()

    targets = reading_service.visible_sentences(
        reading_service.suggestion_targets(sentences, payload.sentence_indexes),
        reading_service.hidden_sentence_indexes(db, user, document),
    )
    by_sentence: dict[int, list[SuggestedSpanOut]] = {}
    model_hits = 0
    for index, spans, from_model in reading_service.iter_suggestions(
        targets, user.cefr_level, provider
    ):
        model_hits += 1 if from_model else 0
        if spans:
            by_sentence[index] = [SuggestedSpanOut.model_validate(span) for span in spans]

    return SuggestOut(
        by_sentence=by_sentence,
        generated=model_hits == len(targets) and not provider.is_mock,
        fallback_count=len(targets) - model_hits,
        sentence_count=len(targets),
    )


@router.post(
    "/materials/{kind}/{material_id}/suggest",
    response_model=SuggestOut,
)
def suggest_annotations(
    kind: str,
    material_id: int,
    payload: SuggestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> SuggestOut:
    """给原文提标注建议：哪些词/搭配/结构值得标。

    只建议不落库；用户点「采纳」时才走 /notes 写成真正的批注。
    逐句慢慢出的版本见 /suggest/stream。
    """
    return _collect_suggestions(db, user, kind, material_id, payload, provider)


def _suggest_events(
    user_id: int,
    kind: str,
    material_id: int,
    sentence_indexes: list[int],
    provider,
) -> Iterator[str]:
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            yield reading_service.sse_event("error", {"detail": "登录状态已失效，请重新登录"})
            return

        try:
            document = _resolve_document(db, user, kind, material_id)
        except HTTPException as exc:
            yield reading_service.sse_event("error", {"detail": exc.detail})
            return

        yield from reading_service.stream_suggestions(
            db,
            user,
            document,
            provider=provider,
            sentence_indexes=sentence_indexes,
            hidden=reading_service.hidden_sentence_indexes(db, user, document),
        )
        db.commit()
    except Exception:  # noqa: BLE001 - 流已开始，异常只能记日志后断开
        logger.exception("标注建议流式响应异常")
        db.rollback()
    finally:
        db.close()


@router.get("/materials/{kind}/{material_id}/suggest/stream")
def suggest_stream(
    kind: str,
    material_id: int,
    sentence_indexes: list[int] = Query(default_factory=list),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> StreamingResponse:
    """标注建议的渐进式返回（SSE）。

    整篇等齐再返回时，用户要对着「挑选中…」等所有句子都过一遍模型。这里改成
    跑完一句发一句，建议一到就先画在对应句子上。

    与 /analyze/stream 一样用 GET、走 fetch 流式读取：EventSource 没法带
    Authorization 头，token 只能塞进 query，会漏进访问日志。
    """
    _resolve_document(db, user, kind, material_id)

    return StreamingResponse(
        _suggest_events(user.id, kind, material_id, sentence_indexes, provider),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/materials/{kind}/{material_id}/analyze-selection",
    response_model=SelectionAnalysisOut,
)
def analyze_selection(
    kind: str,
    material_id: int,
    payload: SelectionAnalyzeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> SelectionAnalysisOut:
    """划词实时解析：给选中的词/短语一条释义和一句可采纳的笔记。

    只做解析不落库；用户点"采纳"时才由 /notes 写成批注。
    """
    document = _resolve_document(db, user, kind, material_id)

    sentence = payload.sentence.strip()
    if not sentence and document.cached_sentences:
        try:
            cached = json.loads(document.cached_sentences)
            for item in cached:
                if item.get("index") == payload.sentence_index:
                    sentence = item.get("text", "")
                    break
        except ValueError:
            sentence = ""

    result, generated = content_service.analyze_selection(
        payload.text, sentence, user.cefr_level, provider
    )
    result["generated"] = generated
    return SelectionAnalysisOut.model_validate(result)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    payload: NoteUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteOut:
    note = reading_service.get_note(db, user, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")

    if payload.note is not None:
        note.note = payload.note
    if payload.meaning is not None:
        note.meaning = payload.meaning
    if payload.color:
        note.color = payload.color
    db.commit()
    return _note_out(note, reading_service.vocabulary_word_set(db, user))


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    note = reading_service.get_note(db, user, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    reading_service.delete_note(db, note)
    db.commit()


@router.post("/notes/{note_id}/to-vocabulary", response_model=NoteOut)
def note_to_vocabulary(
    note_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteOut:
    """把这条笔记里的重点词/搭配加入个人词库。"""
    note = reading_service.get_note(db, user, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")

    word = note.lemma or note.text
    vocabulary_service.save_word(
        db,
        user,
        word=word,
        meaning=note.meaning,
        example=note.note,
        level=user.cefr_level,
        source="reading",
    )
    db.commit()
    return _note_out(note, reading_service.vocabulary_word_set(db, user))


@router.get("/materials/{kind}/{material_id}/export.pdf")
def export_pdf(
    kind: str,
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> Response:
    """导出带批注栏的 PDF：左侧原文，右侧本句的重点词/搭配与个人笔记。"""
    document = _resolve_document(db, user, kind, material_id)

    payload = reading_service.analyze_document(
        db, user, document, provider=provider
    )
    notes = reading_service.list_notes(db, user, document)
    hidden = reading_service.hidden_sentence_indexes(db, user, document)
    sentences = reading_service.visible_sentences(
        reading_service.build_annotations(payload["sentences"], notes), hidden
    )
    db.commit()

    pdf_bytes = pdf_service.build_reading_pdf(
        title=document.title,
        author=document.author_name,
        level=document.level,
        sentences=sentences,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="reading-{material_id}.pdf"'
        },
    )
