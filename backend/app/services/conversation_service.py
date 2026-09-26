"""对话服务：编排场景对话、纠错落库、任务进度、报告生成与 XP 结算。

一轮对话被拆成两路模型调用（回复 / 反馈）并行跑，由 `stream_turn` 渐进式
吐给前端：回复走流式纯文本，首 token 到达就推给用户，不必等整句生成完；
纠错与点评晚几秒到也不影响对话继续。`send_message` 是一次性版本，供非流式
端点与测试使用。
"""

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

    # 开局由 AI 角色说第一句，写入历史
    opening = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=scenario.opening_line,
    )
    db.add(opening)
    db.flush()
    return conversation


# 自由对话的开场句没有对应的 Scenario 记录，但开局消息、启动预热、前端静态音频
# 清单都要用它。收在这一处，别再让 main / 构建脚本各写一遍——那种重复改漏一处，
# 静态音频就会和实际开场白对不上。
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
    """同一场景下已有的对话记录；`scenario_id=None` 表示自由对话。

    「每个场景在历史里只留一条」以前只在列表读取时去重，库里其实会越攒越多；
    重开时要按同一口径把旧的清掉，否则历史里会留下一堆只能靠时间分辨的重复项。
    """
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
    """重开前清掉该场景的旧记录：这一次直接顶上去，历史里不留重复。"""
    for conversation in scene_conversations(db, user, scenario_id=scenario_id):
        db.delete(conversation)
    db.flush()


def pending_hint(scenario: Scenario | None, completed_keys: set[str]) -> dict | None:
    """按当前进度算下一条中文提示。

    提示不落库：它表达的是"下一步该做什么"，随进度实时算出即可，
    也省掉了数据库迁移。未知任务键返回 None，前端隐藏提示卡。
    """
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
    """收集本对话已经推荐过的地道表达，避免重复推送同一条。

    复用已经取回的消息行，不再为此单独查一次库——每轮都在关键路径上。
    """
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
    """一轮对话的公共上下文。

    两路模型调用（回复 / 反馈）共用同一份历史与任务账本，不必各算一遍。
    """

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
    """准备一轮对话：落库用户消息，并按规则算出任务进度账本。

    只 flush 不 commit——流式端点要把「用户消息 + AI 回复」先提交出去，
    这样用户在等反馈的时候刷新页面也能看到 AI 说过什么。

    任务判定全部走规则引擎（零成本、可复现），模型只在反馈那一路上补充
    「它认为完成了哪些」。
    """
    if conversation.is_completed:
        raise ValueError("该对话已结束")

    scenario = conversation.scenario if conversation.scenario_id else None
    # 消息行取一次就够：历史与「已推荐过的表达」都从这批行里算，省一次查询
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
    """落库 AI 回复。此时模型给的反馈可能还没回来。

    提示先用本地规则算的那条顶上：用户不必等反馈就有一句中文脚手架。
    模型那条更贴合当前对话的会在 persist_feedback 里覆盖掉。
    """
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
    """落库反馈、纠错、新词与 XP，返回本轮反馈部分的 payload。"""
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

    # 新词自动进入个人词库，形成"对话 → 词库"闭环
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

    # 模型认定的完成项与规则判定取并集：模型偶尔能听出规则匹配不到的表达
    model_completed = set(feedback.get("completed_task_keys") or [])
    if model_completed:
        merged = completed_task_keys(conversation) | model_completed
        conversation.completed_tasks = json.dumps(sorted(merged), ensure_ascii=False)

    db.flush()

    return {
        "correction": correction,
        "natural_expression": natural,
        "new_vocabulary": [{**v, "is_new": True} for v in vocabulary],
        "coach_note": coach,
        "hint": feedback.get("hint"),
        "task_progress": conversation.task_progress,
        "task_completed": ctx.plan.task_completed,
        "completed_tasks": sorted(completed_task_keys(conversation)),
    }


def stream_turn(
    db: Session,
    user: User,
    conversation: Conversation,
    text: str,
    provider: AIProvider | None = None,
) -> Iterator[tuple[str, dict]]:
    """一轮对话的渐进式返回：先流式吐回复，再给反馈。

    回复走流式纯文本（stream_text）：首 token 到达就往前端推，用户不必等
    整句生成完才看到 AI 开口——这是「AI 回复太慢」的主要体感来源。
    反馈那一路同时并行跑，回复流完后才 yield 反馈。

    帧序：reply_chunk（逐块文本）× N → reply（完整回复，已落库）→
    feedback（纠错、点评等）→ done。前端边收 reply_chunk 边拼显示，
    reply 帧到达后用落库的完整消息替换占位。
    """
    ctx = begin_turn(db, conversation, text, provider)
    # 用户那句话先落库：哪怕后面模型全挂了，也不该把用户说的丢掉
    db.commit()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        # 反馈那一路并行跑
        feedback_future = pool.submit(
            ctx.agent.feedback,
            scenario=ctx.scenario,
            history=ctx.history,
            user_message=text,
            cefr_level=user.cefr_level,
            plan=ctx.plan,
            suggested_expressions=ctx.suggested,
        )

        # 回复走流式：逐块 yield，边生成边推给前端
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
        # 离线模式流式只 yield 一次（整句），strip 后可能为空——走规则引擎兜底
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
        # 客户端中途断开时别把线程等在这里：让模型请求自己跑完即可
        pool.shutdown(wait=False)


def send_message(
    db: Session,
    user: User,
    conversation: Conversation,
    text: str,
    provider: AIProvider | None = None,
) -> dict:
    """一次拿全回复与反馈。非流式端点用，行为与拆分前一致。"""
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
    # 反馈里的 hint / task_progress 覆盖掉 persist_reply 里的本地兜底值
    return {**payload, **persist_feedback(db, user, conversation, ctx, feedback)}


def finish_conversation(
    db: Session,
    user: User,
    conversation: Conversation,
    provider: AIProvider | None = None,
) -> dict:
    """结束对话：生成报告、结算 XP、更新 Streak、解锁成就。"""
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
    # 完成度影响 XP，但保底给一半，避免挫败感
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

    # 完成场景推进「今日任务」的场景子项；该子项的 10 XP 由 settle_daily_task 统一发。
    # 成就由 award_xp 内部统一检查，这里不再单独调用。
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
