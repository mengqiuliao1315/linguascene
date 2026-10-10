import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import WordExplanation
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)


class VocabularyAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def explain(
        self, word: str, context: str = "", cefr_level: str = "B1"
    ) -> WordExplanation:
        cleaned = word.strip().lower()
        key = cache_key(
            "word", "v3", cefr_level, cleaned, context.strip(), self.provider.signature
        )
        cached = self.cache.get(key)
        if cached:
            return WordExplanation.model_validate(cached)

        explanation, from_model = self._explain_uncached(cleaned, context, cefr_level)
        if from_model:
            self.cache.set(key, explanation.model_dump(), ttl_seconds=604800)
        return explanation

    def _explain_uncached(
        self, word: str, context: str, cefr_level: str
    ) -> tuple[WordExplanation, bool]:
        if not self.provider.is_mock:
            try:
                system = render_prompt(
                    "vocabulary_agent", word=word, context=context, cefr_level=cefr_level
                )
                raw = self.provider.complete_json_fast(
                    system,
                    f"Explain the word: {word}",
                    WordExplanation,
                    max_tokens=800,
                )
                if raw:
                    return WordExplanation.model_validate(raw), True
            except (AIProviderError, ValueError) as exc:
                logger.warning("VocabularyAgent 模型调用失败，降级到词典：%s", exc)
                return self._offline_explain(word, context, cefr_level), False

        return self._offline_explain(word, context, cefr_level), True

    def _offline_explain(
        self, word: str, context: str, cefr_level: str
    ) -> WordExplanation:
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
