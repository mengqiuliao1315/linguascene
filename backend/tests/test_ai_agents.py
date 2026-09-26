from app.ai.agents.scenario_agent import ScenarioAgent
from app.ai.agents.sentence_agent import SentenceAgent
from app.ai.rule_engine import (
    TASK_HINTS,
    detect_correction,
    extract_vocabulary,
    task_hint,
    translate_sentence,
)
from app.ai.schemas import (
    ArticleAnalysisOut,
    ConversationReport,
    ScenarioHint,
    ScenarioReply,
    SentenceAnalysis,
    WordExplanation,
)


def test_all_agent_schemas_are_serializable():
    for schema in (
        ScenarioReply,
        WordExplanation,
        SentenceAnalysis,
        ArticleAnalysisOut,
        ConversationReport,
    ):
        data = schema.model_json_schema()
        assert data["type"] == "object"


def test_scenario_reply_schema_shape():
    reply = ScenarioReply(
        reply="What size would you like?",
        correction=None,
        task_progress=25,
        task_completed=False,
    )
    payload = reply.model_dump()
    assert set(payload) >= {
        "reply",
        "correction",
        "natural_expression",
        "new_vocabulary",
        "task_progress",
        "task_completed",
    }
    assert payload["task_progress"] == 25


def test_correction_detects_past_tense_error():
    result = detect_correction("I yesterday go to the coffee shop.")
    assert result is not None
    assert result["severity"] == 1
    assert "went" in result["corrected"]


def test_correction_marks_unnatural_not_wrong():
    result = detect_correction("I want a coffee.")
    assert result is not None
    assert result["severity"] == 2
    assert result["corrected"].startswith("I'd like")


def test_correction_is_silent_on_good_sentence():
    assert detect_correction("Could I get a large latte, please?") is None


def test_correction_does_not_over_correct():
    for sentence in [
        "Yes, please.",
        "Thank you very much.",
        "That sounds great.",
        "I'd like a coffee, please.",
    ]:
        assert detect_correction(sentence) is None, sentence


def test_vocabulary_extraction_respects_level():
    text = "The adaptive system offers personalized practice for every learner."
    hits = extract_vocabulary(text, "B2", limit=5)
    words = {h["word"] for h in hits}
    assert "adaptive" in words or "personalized" in words


def test_vocabulary_extraction_skips_stopwords():
    hits = extract_vocabulary("I would like to have the coffee and the menu", "A2", limit=5)
    words = {h["word"] for h in hits}
    assert "the" not in words
    assert "would" not in words


def test_every_task_hint_is_complete():
    assert len(TASK_HINTS) == 72
    for key, hint in TASK_HINTS.items():
        assert hint["idea_zh"], key
        assert hint["suggested_zh"], key
        assert hint["suggested_en"], key


def test_task_hint_returns_none_for_unknown_key():
    assert task_hint("not-a-real-task") is None
    assert task_hint("") is None


def test_task_hint_carries_key():
    hint = task_hint("choose_drink")
    assert hint is not None
    assert hint["task_key"] == "choose_drink"


def test_scenario_reply_accepts_hint():
    reply = ScenarioReply(
        reply="What size would you like?",
        hint=ScenarioHint(
            task_key="choose_size",
            idea_zh="告诉对方你要的杯型。",
            suggested_zh="我要一个大杯的。",
            suggested_en="A large one, please.",
        ),
    )
    payload = reply.model_dump()
    assert payload["hint"]["task_key"] == "choose_size"


def test_every_task_question_has_chinese():
    agent = ScenarioAgent.__new__(ScenarioAgent)
    for key in TASK_HINTS:
        question = agent._task_question(key)
        assert translate_sentence(question), key


def test_offline_sentence_agent_translates_known_sentence():
    agent = ScenarioAgent.__new__(ScenarioAgent)
    question = agent._task_question("choose_drink")
    result = SentenceAgent().analyze(question, "A2")
    assert result.chinese_meaning
    assert result.chinese_meaning == translate_sentence(question)


def test_offline_sentence_agent_leaves_unknown_sentence_blank():
    result = SentenceAgent().analyze("Totally unheard sentence xyzzy.", "A2")
    assert result.chinese_meaning == ""


def test_translate_sentence_restores_got_it_prefix():
    agent = ScenarioAgent.__new__(ScenarioAgent)
    question = agent._task_question("choose_size")
    assert translate_sentence(f"Got it. {question}") == translate_sentence(question)


def _agent_source_dir():
    import app.ai.agents as agents_pkg
    from pathlib import Path

    return Path(agents_pkg.__file__).parent


def _stub_provider(payload):
    from app.ai.provider import AIProvider

    class Stub(AIProvider):
        name = "stub"
        model = "stub-model"

        def __init__(self):
            self.seen: list[str] = []

        def complete_json(self, system_prompt, user_prompt, schema, *, max_tokens=None):
            self.seen.append(system_prompt)
            return payload

        def complete_json_fast(self, system_prompt, user_prompt, schema, *, max_tokens=None):
            return self.complete_json(
                system_prompt, user_prompt, schema, max_tokens=max_tokens
            )

    return Stub()


def test_every_agent_prompt_file_exists():
    import re
    from app.ai.prompts import PROMPTS_DIR, load_prompt

    names = set()
    for path in _agent_source_dir().glob("*.py"):
        names |= set(
            re.findall(r'render_prompt\(\s*"([^"]+)"', path.read_text(encoding="utf-8"))
        )

    assert names, "没有从 Agent 源码里扫描到任何 prompt 引用"
    for name in sorted(names):
        prompt_file = PROMPTS_DIR / f"{name}.md"
        assert prompt_file.exists(), f"缺少 prompt 文件：{prompt_file}"
        assert load_prompt(name).strip(), f"{prompt_file} 是空文件"


def test_missing_prompt_raises_value_error():
    import pytest

    from app.ai.prompts import render_prompt

    with pytest.raises(ValueError):
        render_prompt("definitely_not_a_real_prompt")


def test_agents_use_model_when_provider_is_online():
    import re

    from app.ai.agents.article_agent import ArticleAgent
    from app.ai.agents.correction_agent import CorrectionAgent
    from app.ai.agents.vocabulary_agent import VocabularyAgent

    cases = [
        (
            ArticleAgent,
            "analyze",
            {"summary": "植物靠根吸水。", "level": "B1"},
            {"content": "Plants absorb water. They need it to grow."},
        ),
        (
            VocabularyAgent,
            "explain",
            {"word": "absorb", "core_meanings": ["吸收"]},
            {"word": "absorb", "context": "Plants absorb water.", "cefr_level": "B1"},
        ),
        (
            SentenceAgent,
            "analyze",
            {"sentence": "Plants absorb water.", "chinese_meaning": "植物吸收水分。"},
            {"sentence": "Plants absorb water.", "cefr_level": "B1"},
        ),
        (
            CorrectionAgent,
            "analyze",
            {"has_error": True, "corrected": "He goes to school."},
            {"text": "He go to school.", "cefr_level": "B1"},
        ),
    ]

    for agent_cls, method, payload, kwargs in cases:
        provider = _stub_provider(payload)
        result = getattr(agent_cls(provider=provider), method)(**kwargs)

        assert provider.seen, f"{agent_cls.__name__} 没走模型分支"
        system = provider.seen[0]
        assert "{schema}" in system, f"{agent_cls.__name__} 的 prompt 缺 {{schema}}"
        leftovers = re.findall(r"\{(?!schema\})[a-z_]+\}", system)
        assert not leftovers, f"{agent_cls.__name__} 有未替换占位符：{set(leftovers)}"
        assert result is not None, f"{agent_cls.__name__} 在线分支返回了 None"


def _batch_payload(sentences):
    return {
        "sentences": [
            {"sentence": s, "chinese_meaning": f"译文{i}"} for i, s in enumerate(sentences)
        ]
    }


import itertools as _itertools

_batch_stub_ids = _itertools.count()


def _batch_stub(payload):
    from app.ai.provider import AIProvider

    class Stub(AIProvider):
        name = "batch-stub"

        def __init__(self):
            self.seen: list[str] = []
            self.fast_seen = 0
            self._sig = f"batch-stub-{next(_batch_stub_ids)}"

        @property
        def signature(self) -> str:
            return self._sig

        def complete_json(self, system_prompt, user_prompt, schema, *, max_tokens=None):
            self.seen.append(system_prompt)
            return payload

        def complete_json_fast(self, system_prompt, user_prompt, schema, *, max_tokens=None):
            self.fast_seen += 1
            self.seen.append(system_prompt)
            return payload

    return Stub()


def _seed_sentence_cache(agent: "SentenceAgent", sentence: str, level: str = "B1") -> None:
    from app.core.cache import cache_key

    key = cache_key("sentence", "v2", level, sentence, agent.provider.signature)
    analysis = SentenceAnalysis(sentence=sentence, chinese_meaning="缓存命中")
    agent.cache.set(key, analysis.model_dump(), ttl_seconds=604800)


def test_sentence_agent_batch_calls_model_once_for_multiple_sentences():
    sentences = ["Plants absorb water.", "They need it to grow.", "Roots take up minerals."]

    provider = _batch_stub(_batch_payload(sentences))
    results = SentenceAgent(provider=provider).analyze_batch_with_status(sentences, "B1")

    assert len(results) == len(sentences)
    assert [r[0].sentence for r in results] == sentences
    assert all(from_model for _, from_model in results)
    assert len(provider.seen) == 1


def test_sentence_agent_batch_reuses_cache_without_calling_model():
    sentences = ["Cached sentence here.", "Brand new sentence."]
    provider = _batch_stub(_batch_payload([sentences[1]]))
    agent = SentenceAgent(provider=provider)
    _seed_sentence_cache(agent, sentences[0])

    results = agent.analyze_batch_with_status(sentences, "B1")

    assert len(results) == 2
    assert results[0][0].sentence == sentences[0]
    assert results[1][0].sentence == sentences[1]
    assert len(provider.seen) == 1


def test_sentence_agent_batch_falls_back_when_count_mismatch():
    from app.ai.batch_tuner import get_batch_tuner

    get_batch_tuner()._reset()

    sentences = ["One sentence here.", "Another one follows.", "Third one now."]
    provider = _batch_stub(_batch_payload(sentences[:2]))

    results = SentenceAgent(provider=provider).analyze_batch_with_status(sentences, "B1")

    assert len(results) == len(sentences)
    assert all(r[0].sentence for r in results)
    assert len(provider.seen) == 1 + len(sentences)

    get_batch_tuner()._reset()


def test_sentence_agent_fast_path_uses_fast_provider_call():
    provider = _batch_stub(
        {"sentence": "Solo.", "chinese_meaning": "单句。"}
    )

    result = SentenceAgent(provider=provider).analyze_batch_with_status(
        ["Solo."], "B1", fast=True
    )

    assert result[0][0].sentence == "Solo."
    assert provider.fast_seen == 1


    """只剩一句要分析时不走批量路径，直接走单句，避免无谓的批量包装。"""
    provider = _batch_stub({"sentence": "Solo.", "chinese_meaning": "单句。"})
    results = SentenceAgent(provider=provider).analyze_batch_with_status(["Solo."], "B1")

    assert len(results) == 1
    assert results[0][0].sentence == "Solo."
    assert len(provider.seen) == 1
    assert "batch" not in provider.seen[0].lower()


def test_batch_sizer_starts_conservative_and_probes_up_on_success():
    from app.ai.batch_tuner import AdaptiveBatchSizer, MAX_BATCH, SUCCESS_BEFORE_PROBE

    sizer = AdaptiveBatchSizer()
    assert sizer.current() == (4, 4)

    for _ in range(SUCCESS_BEFORE_PROBE - 1):
        sizer.note_success(4)
    assert sizer.current()[0] == 4

    sizer.note_success(4)
    assert sizer.current()[0] == 5

    for _ in range(100):
        sizer.note_success(sizer.current()[0])
    assert sizer.current()[0] == MAX_BATCH


def test_batch_sizer_shrinks_on_truncation_and_rate_limit():
    from app.ai.batch_tuner import AdaptiveBatchSizer

    sizer = AdaptiveBatchSizer()
    sizer.note_truncation()
    assert sizer.current()[0] == 3
    assert sizer.current()[1] == 4

    sizer.note_rate_limit()
    assert sizer.current()[0] == 2
    assert sizer.current()[1] == 3

    sizer.note_timeout()
    assert sizer.current()[1] == 2


def test_batch_sizer_does_not_change_on_generic_failure():
    from app.ai.batch_tuner import AdaptiveBatchSizer

    sizer = AdaptiveBatchSizer()
    sizer.note_failure()
    assert sizer.current() == (4, 4)


def test_classify_error_recognizes_rate_limit_and_timeout():
    from app.ai.batch_tuner import classify_error

    assert classify_error(RuntimeError("模型调用失败：HTTP 429 Too Many Requests")) == "rate_limit"
    assert classify_error(RuntimeError("模型调用失败：timed out")) == "timeout"
    assert classify_error(RuntimeError("模型调用失败：HTTP 401")) == "failure"
    assert classify_error(RuntimeError("触发了服务商限流")) == "rate_limit"
