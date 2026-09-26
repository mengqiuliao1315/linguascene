import json
import logging
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_user_provider
from app.api.routes.scenarios import scenario_payload
from app.core.database import SessionLocal, get_db
from app.models.learning import Conversation, Message
from app.models.user import User
from app.schemas.learning import ChatRequest, ChatResponse, MessageOut, ReportOut
from app.services import conversation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["conversations"])


def _message_payload(message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "feedback": json.loads(message.feedback_json) if message.feedback_json else None,
    }


def _conversation_payload(conversation) -> dict:
    scenario = conversation.scenario
    return {
        "id": conversation.id,
        "mode": conversation.mode,
        "task_progress": conversation.task_progress,
        "is_completed": conversation.is_completed,
        "xp_earned": conversation.xp_earned,
        "started_at": conversation.started_at,
        "finished_at": conversation.finished_at,
        "scenario": scenario_payload(scenario) if scenario else None,
        "hint": conversation_service.pending_hint(
            scenario, conversation_service.completed_task_keys(conversation)
        ),
    }


@router.post("/scenarios/{scenario_id}/start")
def start_scenario(
    scenario_id: int,
    restart: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    scenario = conversation_service.get_scenario(db, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="场景不存在")

    if restart:
        conversation_service.clear_scene_conversations(
            db, user, scenario_id=scenario.id
        )

    conversation = conversation_service.start_conversation(db, user, scenario)
    db.commit()
    db.refresh(conversation)

    detail = conversation_service.conversation_detail(db, conversation)
    return {
        **_conversation_payload(conversation),
        "messages": [_message_payload(m) for m in detail["messages"]],
    }


@router.post("/conversations/free-talk/start")
def start_free_talk(
    restart: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if restart:
        conversation_service.clear_scene_conversations(db, user, scenario_id=None)

    conversation = conversation_service.start_free_talk(db, user)
    db.commit()
    db.refresh(conversation)

    detail = conversation_service.conversation_detail(db, conversation)
    return {
        **_conversation_payload(conversation),
        "messages": [_message_payload(m) for m in detail["messages"]],
    }


def _best_progress(conversation: Conversation) -> int:
    return 100 if conversation.is_completed else conversation.task_progress


PREVIEW_LIMIT = 40

FREE_TALK_KEY = "free_talk"


def _preview(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= PREVIEW_LIMIT else f"{collapsed[:PREVIEW_LIMIT]}…"


def _activity_stats(db: Session, conversation_ids: list[int]) -> tuple[dict[int, datetime], dict[int, str]]:
    last_ids = dict(
        db.execute(
            select(Message.conversation_id, func.max(Message.id))
            .where(Message.conversation_id.in_(conversation_ids))
            .group_by(Message.conversation_id)
        ).all()
    )
    first_user_ids = dict(
        db.execute(
            select(Message.conversation_id, func.min(Message.id))
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.role == "user",
            )
            .group_by(Message.conversation_id)
        ).all()
    )

    wanted = [*last_ids.values(), *first_user_ids.values()]
    rows_by_id = (
        {
            message.id: message
            for message in db.execute(
                select(Message).where(Message.id.in_(wanted))
            ).scalars()
        }
        if wanted
        else {}
    )

    last_at: dict[int, datetime] = {}
    previews: dict[int, str] = {}
    for conversation_id, message_id in last_ids.items():
        message = rows_by_id.get(message_id)
        if message is not None:
            last_at[conversation_id] = message.created_at
    for conversation_id, message_id in first_user_ids.items():
        message = rows_by_id.get(message_id)
        if message is not None:
            previews[conversation_id] = _preview(message.content)
    return last_at, previews


@router.get("/conversations")
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    rows = db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.started_at.desc())
        .limit(200)
    ).scalars().all()
    if not rows:
        return []

    last_at, previews = _activity_stats(db, [c.id for c in rows])

    def activity(conversation: Conversation) -> datetime:
        return last_at.get(conversation.id) or conversation.started_at

    def entry(
        conversation: Conversation,
        *,
        task_progress: int,
        is_completed: bool,
        xp_earned: int,
        preview: str,
    ) -> dict:
        return {
            "id": conversation.id,
            "mode": conversation.mode,
            "scenario_id": conversation.scenario_id,
            "scenario_title": (
                conversation.scenario.title if conversation.scenario else "Free Talk"
            ),
            "scenario_icon": (
                conversation.scenario.icon if conversation.scenario else "💬"
            ),
            "task_progress": task_progress,
            "is_completed": is_completed,
            "xp_earned": xp_earned,
            "started_at": conversation.started_at,
            "finished_at": conversation.finished_at,
            "last_message_at": activity(conversation),
            "preview": preview,
        }

    groups: dict[int | str, list[Conversation]] = {}
    merged: list[dict] = []
    for conversation in rows:
        key: int | str = (
            conversation.scenario_id
            if conversation.scenario_id is not None
            else FREE_TALK_KEY
        )
        groups.setdefault(key, []).append(conversation)

    for key, group in groups.items():
        latest = max(group, key=activity)
        if key == FREE_TALK_KEY:
            merged.append(
                entry(
                    latest,
                    task_progress=latest.task_progress,
                    is_completed=latest.is_completed,
                    xp_earned=latest.xp_earned,
                    preview=previews.get(latest.id, ""),
                )
            )
            continue
        merged.append(
            entry(
                latest,
                task_progress=max(_best_progress(c) for c in group),
                is_completed=any(c.is_completed for c in group),
                xp_earned=max(c.xp_earned for c in group),
                preview=previews.get(latest.id, ""),
            )
        )

    merged.sort(key=lambda item: item["last_message_at"], reverse=True)
    return merged


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    conversation = conversation_service.get_conversation(db, user, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    detail = conversation_service.conversation_detail(db, conversation)
    return {
        **_conversation_payload(conversation),
        "messages": [_message_payload(m) for m in detail["messages"]],
    }


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除一次历史对话。消息与纠错随对话一起级联删除，不可恢复。"""
    conversation = conversation_service.get_conversation(db, user, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    db.delete(conversation)
    db.commit()


@router.post("/conversations/{conversation_id}/message", response_model=ChatResponse)
def send_message(
    conversation_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> ChatResponse:
    conversation = conversation_service.get_conversation(db, user, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    try:
        result = conversation_service.send_message(
            db, user, conversation, payload.message, provider
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    return ChatResponse(
        user_message=MessageOut(
            id=result["user_message"].id,
            role="user",
            content=result["user_message"].content,
            created_at=result["user_message"].created_at,
            feedback={
                "correction": result["correction"],
                "natural_expression": result["natural_expression"],
                "new_vocabulary": result["new_vocabulary"],
                "coach_note": result["coach_note"],
            },
        ),
        ai_message=MessageOut(
            id=result["ai_message"].id,
            role="assistant",
            content=result["ai_message"].content,
            created_at=result["ai_message"].created_at,
        ),
        correction=result["correction"],
        natural_expression=result["natural_expression"],
        new_vocabulary=result["new_vocabulary"],
        hint=result["hint"],
        coach_note=result["coach_note"],
        task_progress=result["task_progress"],
        task_completed=result["task_completed"],
        completed_tasks=result["completed_tasks"],
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _turn_payload(payload: dict) -> dict:
    return {
        key: (_message_payload(value) if isinstance(value, Message) else value)
        for key, value in payload.items()
    }


def _turn_events(
    user_id: int, conversation_id: int, text: str, provider
) -> Iterator[str]:
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        conversation = conversation_service.get_conversation(db, user, conversation_id)
        if conversation is None:
            yield _sse("error", {"detail": "对话不存在"})
            return

        for event, payload in conversation_service.stream_turn(
            db, user, conversation, text, provider
        ):
            yield _sse(event, _turn_payload(payload))
    except ValueError as exc:
        db.rollback()
        yield _sse("error", {"detail": str(exc)})
    except Exception:  # noqa: BLE001 - 响应头已发出，异常只能当事件发
        logger.exception("流式对话失败")
        db.rollback()
        yield _sse("error", {"detail": "生成失败，请重试"})
    finally:
        db.close()


@router.post("/conversations/{conversation_id}/message/stream")
def stream_message(
    conversation_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> StreamingResponse:
    """一轮对话的渐进式返回（SSE）。

    帧序：`reply`（AI 这一轮说的话，已落库）→ `feedback`（纠错、地道表达、
    新词、点评、下一步提示）→ `done`。两路模型调用在后端并行跑，回复那一路
    的输出只有一句话，所以用户不必等反馈一起算完才看到 AI 开口。

    权限与「对话是否已结束」先用请求这条会话校验：一旦开始吐帧，响应头就
    已经发出去了，那时再报错前端只能看到断流。
    """
    conversation = conversation_service.get_conversation(db, user, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")
    if conversation.is_completed:
        raise HTTPException(status_code=400, detail="该对话已结束")

    return StreamingResponse(
        _turn_events(user.id, conversation_id, payload.message, provider),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/conversations/{conversation_id}/finish", response_model=ReportOut)
def finish_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> ReportOut:
    conversation = conversation_service.get_conversation(db, user, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    report = conversation_service.finish_conversation(
        db, user, conversation, provider
    )
    db.commit()
    return ReportOut.model_validate(report)
