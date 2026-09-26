"""词汇解释 Agent。结果进缓存，同一个词只调用一次模型。

只缓存模型产出的版本：模型在但调用失败时退回的那份词典结果不一定对
（词形、语境义都可能缺），缓存它等于把一次失败钉死成一周的答案。
"""

import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import WordExplanation
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)


class VocabularyAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        # 传入用户自己的 provider；不传则回落到环境变量兜底实例
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def explain(
        self, word: str, context: str = "", cefr_level: str = "B1"
    ) -> WordExplanation:
        cleaned = word.strip().lower()
        key = cache_key("word", "v2", cefr_level, cleaned, self.provider.signature)
        cached = self.cache.get(key)
        if cached:
            return WordExplanation.model_validate(cached)

        explanation, from_model = self._explain_uncached(cleaned, context, cefr_level)
        # 模型失败的空结果不缓存：一次超时会被钉死成一周的「暂无释义」
        if from_model:
            self.cache.set(key, explanation.model_dump(), ttl_seconds=604800)
        return explanation

    def _explain_uncached(
        self, word: str, context: str, cefr_level: str
    ) -> tuple[WordExplanation, bool]:
        """返回 (解释, 是否权威可缓存)。模型失败的兜底不缓存。"""
        if not self.provider.is_mock:
            try:
                system = render_prompt(
                    "vocabulary_agent", word=word, context=context, cefr_level=cefr_level
                )
                # 划词只为尽快看到中文意思：只试一次，不走完整的四次重试预算
                raw = self.provider.complete_json_fast(
                    system,
                    f"Explain the word: {word}",
                    WordExplanation,
                    max_tokens=500,
                )
                if raw:
                    return WordExplanation.model_validate(raw), True
            except (AIProviderError, ValueError) as exc:
                logger.warning("VocabularyAgent 模型调用失败，降级到词典：%s", exc)
                return self._offline_explain(word, context, cefr_level), False

        # 离线规则引擎的结果是确定的，可以缓存
        return self._offline_explain(word, context, cefr_level), True

    def _offline_explain(
        self, word: str, context: str, cefr_level: str
    ) -> WordExplanation:
        """离线：只从分级词表里查。查不到就如实说明，不编造释义。"""
        for level, lexicon in rule_engine.VOCAB_BY_LEVEL.items():
            if word in lexicon:
                return WordExplanation(
                    word=word,
                    pronunciation="",
                    part_of_speech="",
                    core_meanings=[lexicon[word]],
                    meaning_in_context=lexicon[word] if context else "",
                    collocations=[],
                    example_sentences=[context] if context else [],
                    related_words=[],
                    cefr_level=level,
                )
        return WordExplanation(
            word=word,
            cefr_level=cefr_level,
            core_meanings=[],
            meaning_in_context="",
            example_sentences=[context] if context else [],
        )
