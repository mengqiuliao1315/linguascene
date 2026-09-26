import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import rule_engine
from app.ai.agents import ReportAgent, ScenarioAgent
from app.ai.agents.scenario_agent import TurnPlan
from app.ai.provider import AIProvider
from app.models.learning import (
    Conversation,
    Correction,
    Message,
    Scenario,
)
from app.models.user import User
from app.services import gamification_service, levels, vocabulary_service, wordbook_service


def get_scenario(db: Session, scenario_id: int) -> Scenario | None:
    return db.execute(
        select(Scenario).where(Scenario.id == scenario_id, Scenario.is_published.is_(True))
    ).scalar_one_or_none()


def start_conversation(db: Session, user: User, scenario: Scenario) -> Conversation:
    conversation = Conversation(
        user_id=user.id,
        scenario_id=scenario.id,
        mode="scenario",
        state_json="{}",
        completed_tasks="[]",
        task_progress=0,
    )
    db.add(conversation)
    db.flush()

    opening = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=scenario.opening_line,
    )
    db.add(opening)
    db.flush()
    return conversation


FREE_TALK_OPENING = "Hey! What would you like to talk about today?"


def start_free_talk(db: Session, user: User) -> Conversation:
    conversation = Conversation(
        user_id=user.id, scenario_id=None, mode="free_talk", state_json="{}",
        completed_tasks="[]", task_progress=0,
    )
    db.add(conversation)
    db.flush()
    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=FREE_TALK_OPENING,
        )
    )
    db.flush()
    return conversation


def get_conversation(db: Session, user: User, conversation_id: int) -> Conversation | None:
    return db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    ).scalar_one_or_none()


def scene_conversations(
    db: Session, user: User, *, scenario_id: int | None
) -> list[Conversation]:
    stmt = select(Conversation).where(Conversation.user_id == user.id)
    if scenario_id is None:
        stmt = stmt.where(
            Conversation.scenario_id.is_(None), Conversation.mode == "free_talk"
        )
    else:
        stmt = stmt.where(Conversation.scenario_id == scenario_id)
    return list(db.execute(stmt).scalars().all())


def clear_scene_conversations(
    db: Session, user: User, *, scenario_id: int | None
) -> None:
    for conversation in scene_conversations(db, user, scenario_id=scenario_id):
        db.delete(conversation)
    db.flush()


def pending_hint(scenario: Scenario | None, completed_keys: set[str]) -> dict | None:
    if not scenario or not scenario.tasks:
        return None

    for task in sorted(scenario.tasks, key=lambda t: t.task_order):
        if task.task_key in completed_keys:
            continue
        hint = rule_engine.task_hint(task.task_key)
        if not hint:
            return None
        hint["task_description"] = task.description
        return hint
    return None


def completed_task_keys(conversation: Conversation) -> set[str]:
    try:
        return set(json.loads(conversation.completed_tasks or "[]"))
    except json.JSONDecodeError:
        return set()


def _messages(db: Session, conversation: Conversation) -> list[Message]:
    return db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.id)
    ).scalars().all()


def _history(db: Session, conversation: Conversation) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in _messages(db, conversation)]


def _suggested_expressions(messages: list[Message]) -> set[str]:
    suggested: set[str] = set()
    for message in messages:
        if not message.feedback_json:
            continue
        try:
            feedback = json.loads(message.feedback_json)
        except (TypeError, json.JSONDecodeError):
            continue
        expression = (feedback.get("natural_expression") or {}).get("expression")
        if expression:
            suggested.add(expression)
    return suggested


@dataclass
class TurnContext:

    agent: ScenarioAgent
    scenario: Scenario | None
    history: list[dict]
    user_message: Message
    suggested: set[str]
    plan: TurnPlan


def begin_turn(
    db: Session,
    conversation: Conversation,
    text: str,
    provider: AIProvider | None = None,
) -> TurnContext:
    if conversation.is_completed:
        raise ValueError("该对话已结束")

    scenario = conversation.scenario if conversation.scenario_id else None
    history_rows = _messages(db, conversation)
    history = [{"role": m.role, "content": m.content} for m in history_rows]

    agent = ScenarioAgent(provider)
    plan = agent.plan(
        scenario=scenario,
        user_message=text,
        completed_tasks=completed_task_keys(conversation),
        task_progress=conversation.task_progress,
    )

    user_message = Message(conversation_id=conversation.id, role="user", content=text)
    db.add(user_message)
    db.flush()

    return TurnContext(
        agent=agent,
        scenario=scenario,
        history=history,
        user_message=user_message,
        suggested=_suggested_expressions(history_rows),
        plan=plan,
    )


def persist_reply(
    db: Session,
    user: User,
    conversation: Conversation,
    ctx: TurnContext,
    reply: str,
) -> dict:
    plan = ctx.plan
    conversation.completed_tasks = json.dumps(
        sorted(plan.all_completed), ensure_ascii=False
    )
    conversation.task_progress = plan.progress

    ai_message = Message(
        conversation_id=conversation.id, role="assistant", content=reply
    )
    db.add(ai_message)
    gamification_service.touch_streak(db, user)
    db.flush()

    return {
        "user_message": ctx.user_message,
        "ai_message": ai_message,
        "hint": pending_hint(ctx.scenario, plan.all_completed),
        "task_progress": plan.progress,
        "task_completed": plan.task_completed,
        "completed_tasks": sorted(plan.all_completed),
    }


def persist_feedback(
    db: Session,
    user: User,
    conversation: Conversation,
    ctx: TurnContext,
    feedback: dict,
) -> dict:
    correction = feedback.get("correction")
    natural = feedback.get("natural_expression")
    vocabulary = feedback.get("new_vocabulary") or []
    coach = feedback.get("coach_note")

    ctx.user_message.feedback_json = json.dumps(
        {
            "correction": correction,
            "natural_expression": natural,
            "new_vocabulary": vocabulary,
            "coach_note": coach,
        },
        ensure_ascii=False,
    )

    if correction:
        db.add(
            Correction(
                message_id=ctx.user_message.id,
                original_text=correction["original"],
                corrected_text=correction["corrected"],
                explanation=correction["explanation"],
                correction_type=correction.get("correction_type", "grammar"),
                severity=correction.get("severity", 1),
            )
        )

    for item in vocabulary:
        _, created = vocabulary_service.save_word(
            db,
            user,
            word=item["word"],
            meaning=item.get("meaning", ""),
            phonetic=item.get("phonetic", ""),
            example=item.get("example", ""),
            level=user.cefr_level,
            source="scenario",
        )
        if created:
            gamification_service.award_xp(db, user, levels.XP_REWARDS["new_word"], "new_word")

    valid_keys = {t.task_key for t in (ctx.scenario.tasks if ctx.scenario else [])}
    model_completed = set(feedback.get("completed_task_keys") or [])
    if valid_keys:
        model_completed &= valid_keys
    task_completed = ctx.plan.task_completed
    if model_completed:
        merged = completed_task_keys(conversation) | model_completed
        conversation.completed_tasks = json.dumps(sorted(merged), ensure_ascii=False)
        if ctx.plan.total_tasks:
            conversation.task_progress = min(
                100, int(len(merged) / ctx.plan.total_tasks * 100)
            )
            if conversation.task_progress >= 100:
                task_completed = True

    db.flush()

    return {
        "correction": correction,
        "natural_expression": natural,
        "new_vocabulary": [{**v, "is_new": True} for v in vocabulary],
        "coach_note": coach,
        "hint": feedback.get("hint"),
        "task_progress": conversation.task_progress,
        "task_completed": task_completed,
        "completed_tasks": sorted(completed_task_keys(conversation)),
    }


def stream_turn(
    db: Session,
    user: User,
    conversation: Conversation,
    text: str,
    provider: AIProvider | None = None,
) -> Iterator[tuple[str, dict]]:
    ctx = begin_turn(db, conversation, text, provider)
    db.commit()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        feedback_future = pool.submit(
            ctx.agent.feedback,
            scenario=ctx.scenario,
            history=ctx.history,
            user_message=text,
            cefr_level=user.cefr_level,
            plan=ctx.plan,
            suggested_expressions=ctx.suggested,
        )

        reply_parts: list[str] = []
        for chunk in ctx.agent.reply_core_stream(
            scenario=ctx.scenario,
            history=ctx.history,
            user_message=text,
            cefr_level=user.cefr_level,
            plan=ctx.plan,
        ):
            if chunk:
                reply_parts.append(chunk)
                yield "reply_chunk", {"text": chunk}

        reply = "".join(reply_parts).strip()
        if not reply:
            reply = ctx.agent.reply_core(
                scenario=ctx.scenario,
                history=ctx.history,
                user_message=text,
                cefr_level=user.cefr_level,
                plan=ctx.plan,
            )

        reply_payload = persist_reply(db, user, conversation, ctx, reply)
        db.commit()
        yield "reply", reply_payload

        feedback_payload = persist_feedback(db, user, conversation, ctx, feedback_future.result())
        db.commit()
        yield "feedback", feedback_payload
        yield "done", {
            "task_progress": feedback_payload["task_progress"],
            "task_completed": feedback_payload["task_completed"],
        }
    finally:
        pool.shutdown(wait=False)


def send_message(
    db: Session,
    user: User,
    conversation: Conversation,
    text: str,
    provider: AIProvider | None = None,
) -> dict:
    ctx = begin_turn(db, conversation, text, provider)
    reply = ctx.agent.reply_core(
        scenario=ctx.scenario,
        history=ctx.history,
        user_message=text,
        cefr_level=user.cefr_level,
        plan=ctx.plan,
    )
    payload = persist_reply(db, user, conversation, ctx, reply)
    feedback = ctx.agent.feedback(
        scenario=ctx.scenario,
        history=ctx.history,
        user_message=text,
        cefr_level=user.cefr_level,
        plan=ctx.plan,
        suggested_expressions=ctx.suggested,
    )
    return {**payload, **persist_feedback(db, user, conversation, ctx, feedback)}


def finish_conversation(
    db: Session,
    user: User,
    conversation: Conversation,
    provider: AIProvider | None = None,
) -> dict:
    if conversation.finished_at is not None and conversation.report_json:
        return json.loads(conversation.report_json)

    scenario = conversation.scenario if conversation.scenario_id else None
    messages = _history(db, conversation)

    corrections_rows = db.execute(
        select(Correction)
        .join(Message, Message.id == Correction.message_id)
        .where(Message.conversation_id == conversation.id)
    ).scalars().all()
    corrections = [
        {
            "original": c.original_text,
            "corrected": c.corrected_text,
            "explanation": c.explanation,
            "severity": c.severity,
        }
        for c in corrections_rows
    ]

    task_progress = conversation.task_progress
    base_xp = (
        levels.XP_REWARDS["scenario"]
        if conversation.mode == "scenario"
        else levels.XP_REWARDS["free_talk"]
    )
    xp_earned = int(base_xp * (0.5 + 0.5 * task_progress / 100))

    report = ReportAgent(provider).build(
        scenario=scenario,
        messages=messages,
        corrections=corrections,
        task_progress=task_progress,
        cefr_level=user.cefr_level,
        xp_earned=xp_earned,
    )

    conversation.finished_at = datetime.now(timezone.utc)
    conversation.is_completed = True
    conversation.xp_earned = xp_earned
    conversation.score = (
        report.grammar_score
        + report.vocabulary_score
        + report.naturalness_score
        + report.communication_score
    ) / 4

    payload = {
        "conversation_id": conversation.id,
        "scenario_title": scenario.title if scenario else "Free Talk",
        "summary": report.summary,
        "task_progress": task_progress,
        "scores": {
            "grammar": report.grammar_score,
            "vocabulary": report.vocabulary_score,
            "naturalness": report.naturalness_score,
            "communication": report.communication_score,
        },
        "new_words": report.new_words,
        "key_phrases": report.key_phrases,
        "corrections_count": report.corrections_count,
        "xp_earned": xp_earned,
        "streak": user.streak,
    }

    gamification_service.award_xp(db, user, xp_earned, conversation.mode)
    streak = gamification_service.touch_streak(db, user)
    payload["streak"] = streak

    if conversation.mode == "scenario":
        wordbook_service.record_activity(db, user, "scenario", 1)

    conversation.report_json = json.dumps(payload, ensure_ascii=False, default=str)
    db.flush()
    return payload


def conversation_detail(db: Session, conversation: Conversation) -> dict:
    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.id)
    ).scalars().all()

    return {"conversation": conversation, "messages": messages}
