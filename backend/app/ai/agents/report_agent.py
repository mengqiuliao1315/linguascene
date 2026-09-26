import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import ConversationReport
from app.models.learning import Scenario

logger = logging.getLogger(__name__)


class ReportAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()

    def build(
        self,
        *,
        scenario: Scenario | None,
        messages: list[dict],
        corrections: list[dict],
        task_progress: int,
        cefr_level: str,
        xp_earned: int,
    ) -> ConversationReport:
        stats = rule_engine.build_report_stats(messages, corrections, task_progress)

        key_phrases: list[str] = []
        if scenario:
            pool = rule_engine.SCENARIO_EXPRESSIONS.get(scenario.slug, [])
            key_phrases = [expr for expr, _, _ in pool[:3]]

        new_words: list[str] = []
        for message in messages:
            if message.get("role") != "user":
                continue
            for item in rule_engine.extract_vocabulary(
                message.get("content", ""), cefr_level, limit=2
            ):
                if item["word"] not in new_words:
                    new_words.append(item["word"])
        new_words = new_words[:6]

        if not self.provider.is_mock:
            try:
                transcript = "\n".join(
                    f"{'Learner' if m['role'] == 'user' else 'AI'}: {m['content']}"
                    for m in messages[-20:]
                )
                correction_text = "\n".join(
                    f"- {c['original']} -> {c['corrected']}" for c in corrections
                ) or "none"
                system = render_prompt(
                    "report_agent",
                    scenario_title=scenario.title if scenario else "Free Talk",
                    goal=scenario.goal if scenario else "Free conversation",
                    task_progress=task_progress,
                    transcript=transcript,
                    corrections=correction_text,
                )
                raw = self.provider.complete_json(
                    system, "Generate the study report.", ConversationReport
                )
                if raw:
                    report = ConversationReport.model_validate(raw)
                    report.task_progress = task_progress
                    report.corrections_count = stats["corrections_count"]
                    report.xp_earned = xp_earned
                    report.new_words = report.new_words or new_words
                    report.key_phrases = report.key_phrases or key_phrases
                    return report
            except (AIProviderError, ValueError) as exc:
                logger.warning("ReportAgent 模型调用失败，降级到规则引擎：%s", exc)

        return ConversationReport(
            summary=_offline_summary(scenario, task_progress, stats["corrections_count"]),
            task_progress=task_progress,
            grammar_score=stats["grammar_score"],
            vocabulary_score=stats["vocabulary_score"],
            naturalness_score=stats["naturalness_score"],
            communication_score=stats["communication_score"],
            new_words=new_words,
            key_phrases=key_phrases,
            corrections_count=stats["corrections_count"],
            xp_earned=xp_earned,
        )


def _offline_summary(
    scenario: Scenario | None, task_progress: int, corrections_count: int
) -> str:
    title = scenario.title if scenario else "Free Talk"
    if task_progress >= 100:
        return f"{title} 全部任务已完成，本次共记录 {corrections_count} 处表达优化。"
    return f"{title} 完成度 {task_progress}%，本次共记录 {corrections_count} 处表达优化。"
