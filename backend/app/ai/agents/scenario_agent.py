import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import (
    ScenarioFeedback,
    ScenarioReply,
)
from app.models.learning import Scenario

logger = logging.getLogger(__name__)


@dataclass
class TurnPlan:

    pending_keys: list[str] = field(default_factory=list)
    """本轮开始前所有未完成的任务键。"""

    newly_completed: list[str] = field(default_factory=list)
    """规则引擎判定本轮完成了的任务键。"""

    all_completed: set[str] = field(default_factory=set)
    """规则判定下，本轮之后已完成的全集。"""

    remaining_keys: list[str] = field(default_factory=list)
    """本轮之后仍未完成的任务键。"""

    total_tasks: int = 0
    progress: int = 0
    next_key: str | None = None
    task_completed: bool = False


class ScenarioAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()


    def plan(
        self,
        *,
        scenario: Scenario | None,
        user_message: str,
        completed_tasks: set[str],
        task_progress: int = 0,
    ) -> TurnPlan:
        tasks = scenario.tasks if scenario else []
        total_tasks = len(tasks)
        pending_keys = [t.task_key for t in tasks if t.task_key not in completed_tasks]

        newly_completed = rule_engine.detect_completed_tasks(
            user_message, pending_keys, completed_tasks
        )
        all_completed = completed_tasks | set(newly_completed)
        progress = (
            int(len(all_completed) / total_tasks * 100) if total_tasks else task_progress
        )
        remaining_keys = [k for k in pending_keys if k not in all_completed]
        task_completed = bool(total_tasks and len(all_completed) == total_tasks)
        if task_completed:
            progress = 100

        return TurnPlan(
            pending_keys=pending_keys,
            newly_completed=newly_completed,
            all_completed=all_completed,
            remaining_keys=remaining_keys,
            total_tasks=total_tasks,
            progress=progress,
            next_key=remaining_keys[0] if remaining_keys else None,
            task_completed=task_completed,
        )


    def _reply_system_prompt(
        self, scenario: Scenario | None, cefr_level: str, plan: TurnPlan
    ) -> str:
        return render_prompt(
            "scenario_reply",
            ai_role=scenario.ai_role if scenario else "Conversation Partner",
            ai_role_prompt=scenario.ai_role_prompt if scenario else "",
            goal=(
                scenario.goal
                if scenario
                else "Have a natural English conversation"
            ),
            tasks=self._task_lines(scenario),
            completed_tasks=", ".join(sorted(plan.all_completed)) or "none",
            cefr_level=cefr_level,
        )

    def reply_core(
        self,
        *,
        scenario: Scenario | None,
        history: list[dict],
        user_message: str,
        cefr_level: str,
        plan: TurnPlan,
    ) -> str:
        if not self.provider.is_mock:
            try:
                system = self._reply_system_prompt(scenario, cefr_level, plan)
                text = self.provider.complete_text(
                    system,
                    self._build_user_prompt(history, user_message),
                    max_tokens=180,
                )
                if text:
                    return text
            except (AIProviderError, ValueError) as exc:
                logger.warning("ScenarioAgent 回复生成失败，降级到规则引擎：%s", exc)

        return self._offline_reply(
            scenario=scenario,
            user_message=user_message,
            newly_completed=plan.newly_completed,
            pending_keys=plan.remaining_keys,
            all_completed=plan.all_completed,
            history=history,
        )

    def reply_core_stream(
        self,
        *,
        scenario: Scenario | None,
        history: list[dict],
        user_message: str,
        cefr_level: str,
        plan: TurnPlan,
    ) -> Iterator[str]:
        if not self.provider.is_mock:
            try:
                system = self._reply_system_prompt(scenario, cefr_level, plan)
                yield from self.provider.stream_text(
                    system,
                    self._build_user_prompt(history, user_message),
                    max_tokens=180,
                )
                return
            except (AIProviderError, ValueError) as exc:
                logger.warning("ScenarioAgent 流式回复失败，降级：%s", exc)

        yield self._offline_reply(
            scenario=scenario,
            user_message=user_message,
            newly_completed=plan.newly_completed,
            pending_keys=plan.remaining_keys,
            all_completed=plan.all_completed,
            history=history,
        )


    def feedback(
        self,
        *,
        scenario: Scenario | None,
        history: list[dict],
        user_message: str,
        cefr_level: str,
        plan: TurnPlan,
        suggested_expressions: set[str] | None = None,
    ) -> dict:
        correction = None
        natural = None
        vocabulary: list[dict] = []
        model_hint = None
        coach = None
        model_completed: list[str] = []

        if not self.provider.is_mock:
            try:
                system = render_prompt(
                    "scenario_feedback",
                    ai_role=scenario.ai_role if scenario else "Conversation Partner",
                    goal=(
                        scenario.goal
                        if scenario
                        else "Have a natural English conversation"
                    ),
                    tasks=self._task_lines(scenario),
                    completed_tasks=", ".join(sorted(plan.all_completed)) or "none",
                    cefr_level=cefr_level,
                    next_task_key=plan.next_key or "",
                )
                raw = self.provider.complete_json_fast(
                    system,
                    self._build_user_prompt(history, user_message),
                    ScenarioFeedback,
                    max_tokens=700,
                )
                if raw:
                    parsed = ScenarioFeedback.model_validate(raw)
                    correction = (
                        parsed.correction.model_dump()
                        if parsed.correction and parsed.correction.has_error
                        else None
                    )
                    natural = (
                        parsed.natural_expression.model_dump()
                        if parsed.natural_expression
                        and parsed.natural_expression.expression
                        else None
                    )
                    vocabulary = [v.model_dump() for v in parsed.new_vocabulary]
                    model_hint = parsed.hint
                    coach = (
                        parsed.coach_note.model_dump()
                        if parsed.coach_note and parsed.coach_note.message_zh
                        else None
                    )
                    model_completed = list(parsed.completed_task_keys)
            except (AIProviderError, ValueError) as exc:
                logger.warning("ScenarioAgent 反馈生成失败，降级到规则引擎：%s", exc)

        if self.provider.is_mock:
            return {
                "correction": None,
                "natural_expression": None,
                "new_vocabulary": [],
                "hint": self._build_hint(plan.next_key, scenario, None),
                "coach_note": None,
                "completed_task_keys": [],
            }

        if correction is None:
            correction = rule_engine.detect_correction(user_message)

        return {
            "correction": correction,
            "natural_expression": natural,
            "new_vocabulary": vocabulary,
            "hint": self._build_hint(plan.next_key, scenario, model_hint),
            "coach_note": coach,
            "completed_task_keys": model_completed,
        }


    def reply(
        self,
        *,
        scenario: Scenario | None,
        history: list[dict],
        user_message: str,
        cefr_level: str,
        state: dict,
        completed_tasks: set[str],
        task_progress: int,
        suggested_expressions: set[str] | None = None,
    ) -> ScenarioReply:
        plan = self.plan(
            scenario=scenario,
            user_message=user_message,
            completed_tasks=completed_tasks,
            task_progress=task_progress,
        )
        reply_text = self.reply_core(
            scenario=scenario,
            history=history,
            user_message=user_message,
            cefr_level=cefr_level,
            plan=plan,
        )
        feedback = self.feedback(
            scenario=scenario,
            history=history,
            user_message=user_message,
            cefr_level=cefr_level,
            plan=plan,
            suggested_expressions=suggested_expressions,
        )

        return ScenarioReply(
            reply=reply_text,
            correction=feedback["correction"],
            natural_expression=feedback["natural_expression"],
            new_vocabulary=feedback["new_vocabulary"],
            hint=feedback["hint"],
            coach_note=feedback["coach_note"],
            completed_task_keys=feedback["completed_task_keys"],
            task_progress=plan.progress,
            task_completed=plan.task_completed,
        )


    def _task_lines(self, scenario: Scenario | None) -> str:
        if not scenario:
            return "- Free conversation"
        return "\n".join(
            f"- [{task.task_key}] {task.description}" for task in scenario.tasks
        ) or "- Free conversation"

    def _build_hint(
        self,
        next_key: str | None,
        scenario: Scenario | None,
        model_hint=None,
    ) -> dict | None:
        if not next_key:
            return None

        description = ""
        if scenario:
            for task in scenario.tasks:
                if task.task_key == next_key:
                    description = task.description
                    break

        if model_hint and model_hint.suggested_en:
            data = model_hint.model_dump()
            data["task_key"] = next_key
            data["task_description"] = description
            return data

        fallback = rule_engine.task_hint(next_key)
        if not fallback:
            return None
        fallback["task_description"] = description
        return fallback

    def _build_user_prompt(self, history: list[dict], user_message: str) -> str:
        lines = []
        for msg in history[-8:]:
            speaker = "Learner" if msg["role"] == "user" else "You"
            lines.append(f"{speaker}: {msg['content']}")
        lines.append(f"Learner: {user_message}")
        return "\n".join(lines)

    def _offline_reply(
        self,
        *,
        scenario: Scenario | None,
        user_message: str,
        newly_completed: list[str],
        pending_keys: list[str],
        all_completed: set[str],
        history: list[dict],
    ) -> str:
        if scenario and scenario.tasks:
            task_map = {t.task_key: t for t in scenario.tasks}
            if pending_keys:
                next_task = task_map.get(pending_keys[0])
                question = self._task_question(next_task.task_key if next_task else "")
                if newly_completed:
                    return f"Got it. {question}"
                return question
            return self._closing_line(scenario.slug)

        return self._free_talk_reply(user_message, history)

    def _task_question(self, task_key: str) -> str:
        return rule_engine.TASK_QUESTIONS.get(
            task_key, "Could you tell me more about that?"
        )

    def _closing_line(self, slug: str) -> str:
        closings = {
            "ordering-coffee": "Perfect, your order is all set. Here you go — enjoy your drink!",
            "airport-check-in": "You're all checked in. Here's your boarding pass. Have a good flight!",
            "hotel-check-in": "Everything is arranged. Here's your key card. Enjoy your stay!",
            "restaurant": "Great, I'll get that started for you right away.",
            "job-interview": "Thanks, that's everything I needed. We'll be in touch soon.",
            "grocery-shopping": "You're all set. The checkout is right over there. Have a good day!",
            "taxi-ride": "Here we are. That'll be twelve dollars. Have a good evening!",
            "doctor-visit": "Everything looks good here. You're all set!",
            "bank-account": "Everything looks good here. You're all set!",
            "apartment-renting": "Great, I'll send you the paperwork today. Thanks for coming by!",
            "team-meeting": "Great, that covers everything. Thanks for your time today. Take care!",
            "party-small-talk": "It was great talking to you! Enjoy the rest of the party.",
        }
        return closings.get(slug, "Great, that's everything. Well done!")

    def _free_talk_reply(self, user_message: str, history: list[dict]) -> str:
        turn = len([m for m in history if m["role"] == "user"])
        prompts = [
            "That's interesting. Could you tell me more about that?",
            "I see. How did that make you feel?",
            "Nice. What happened next?",
            "Got it. Why do you think that is?",
            "That makes sense. What would you do differently next time?",
        ]
        return prompts[turn % len(prompts)]
