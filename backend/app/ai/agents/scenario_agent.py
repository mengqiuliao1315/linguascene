"""场景对话 Agent。

负责：扮演角色推进剧情、判定任务进度、给出纠错与地道表达。

一次对话回复被拆成两路模型调用：

- `reply_core`：只产出角色这一轮说的话，输出最短，用户最先看到；
- `feedback`：纠错、地道表达、新词、点评、下一步提示，可以晚一点到。

两路并行跑，谁先好谁先发（见 conversation_service.stream_message），
所以「AI 说话」的等待时间只取决于短的那一路。原先把所有字段塞进一次调用，
模型得把整包 JSON 写完才返回，回复也就被反馈一起拖住了。

在线时由模型生成，离线时由规则引擎生成，两者共用同一套任务判定与反馈策略。
"""

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
    """一轮对话的进度账本。

    任务判定全部走规则引擎，不依赖模型，保证进度真实可复现；模型只在这之上
    补充「它认为完成了哪些」。
    """

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

    # ------------------------------------------------------------ 任务判定

    def plan(
        self,
        *,
        scenario: Scenario | None,
        user_message: str,
        completed_tasks: set[str],
        task_progress: int = 0,
    ) -> TurnPlan:
        """按规则算本轮的任务进度。不调用模型，零成本。"""
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

    # ------------------------------------------------------- 第一路：回复

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
        """只产出角色这一轮说的话。模型不可用时退回规则引擎。

        走纯文本补全而非 JSON：不带 response_format、不做 JSON 解析，
        模型直接输出角色台词，比 JSON 模式快 20~30%。
        """
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
        """流式产出角色台词，逐块 yield。

        比 reply_core 更快体感：首 token 到达就往前端推，用户不必等整句
        生成完才看到 AI 开口。模型不可用或流式失败时退回 reply_core
        一次性返回（仍 yield 一次，调用方无感知差异）。
        """
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

        # 离线或流式失败：一次性返回
        yield self._offline_reply(
            scenario=scenario,
            user_message=user_message,
            newly_completed=plan.newly_completed,
            pending_keys=plan.remaining_keys,
            all_completed=plan.all_completed,
            history=history,
        )

    # ------------------------------------------------------- 第二路：反馈

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
        """纠错、地道表达、新词、点评、下一步提示。

        API 不可用（离线模式）时，不生成任何点评——规则引擎的纠错和点评
        太粗糙，给用户看反而误导。只保留任务提示（纯规则、可靠）和进度。
        """
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

        # 离线模式：API 不可用时不给点评。
        # 规则引擎的纠错和点评质量不够，给用户看反而误导——
        # 不如不给，让用户专注对话本身。任务提示仍保留（纯规则、可靠）。
        if self.provider.is_mock:
            return {
                "correction": None,
                "natural_expression": None,
                "new_vocabulary": [],
                "hint": self._build_hint(plan.next_key, scenario, None),
                "coach_note": None,
                "completed_task_keys": [],
            }

        return {
            "correction": correction,
            "natural_expression": natural,
            "new_vocabulary": vocabulary,
            "hint": self._build_hint(plan.next_key, scenario, model_hint),
            "coach_note": coach,
            "completed_task_keys": model_completed,
        }

    # ---------------------------------------------------- 一次拿全（兼容）

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
        """两路合并成一次返回。

        流式端点已经改成分别调用 reply_core / feedback；这里保留给一次性
        端点与测试使用，行为与拆分前一致。
        """
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

    # ------------------------------------------------------------- 工具

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
        """给下一个未完成任务配一条中文提示。

        任务键由本地任务列表决定，不采信模型的 task_key，避免提示跑偏；
        模型只负责把 idea/suggested 写得更贴合当前对话，缺失时回退静态表。
        """
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
            # task_key 与 task_description 一律以本地任务表为准。模型有时会
            # 自行判断进度、把下一步的任务名写进 task_description，导致提示卡
            # 的标题（本地任务）和描述（模型的猜测）对不上。
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
        """离线模式回复：围绕下一个未完成任务提问，保持角色语气。"""
        if scenario and scenario.tasks:
            task_map = {t.task_key: t for t in scenario.tasks}
            if pending_keys:
                next_task = task_map.get(pending_keys[0])
                question = self._task_question(next_task.task_key if next_task else "")
                if newly_completed:
                    return f"Got it. {question}"
                return question
            # 全部完成
            return self._closing_line(scenario.slug)

        # 自由对话：基于用户输入做承接式追问，不编造内容
        return self._free_talk_reply(user_message, history)

    def _task_question(self, task_key: str) -> str:
        """按任务键取固定提问。内容模块是唯一来源，未知键回退到通用追问。"""
        return rule_engine.TASK_QUESTIONS.get(
            task_key, "Could you tell me more about that?"
        )

    def _closing_line(self, slug: str) -> str:
        """全部任务完成后的收尾语，按场景给一句符合角色身份的话。"""
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
        """自由对话：用开放性问题承接，不做语义臆测。"""
        turn = len([m for m in history if m["role"] == "user"])
        prompts = [
            "That's interesting. Could you tell me more about that?",
            "I see. How did that make you feel?",
            "Nice. What happened next?",
            "Got it. Why do you think that is?",
            "That makes sense. What would you do differently next time?",
        ]
        return prompts[turn % len(prompts)]
