import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import WordExplanation, WordLookup
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)


def _expand_lookup(
    lookup: WordLookup, fallback_word: str, cefr_level: str
) -> WordExplanation:
    """把模型的精简结果补齐成完整的 WordExplanation（接口对外形状不变）。"""
    senses = [sense.model_dump() for sense in lookup.senses]
    meanings = [sense.meaning for sense in lookup.senses if sense.meaning.strip()]
    examples = [sense.example for sense in lookup.senses if sense.example.strip()]
    return WordExplanation(
        word=lookup.word or fallback_word.strip().lower(),
        pronunciation=lookup.pronunciation,
        part_of_speech=lookup.senses[0].part_of_speech if lookup.senses else "",
        core_meanings=meanings,
        meaning_in_context=lookup.meaning_in_context,
        collocations=[],
        example_sentences=examples,
        related_words=[],
        cefr_level=cefr_level,
        senses=senses,
    )


class VocabularyAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def explain(
        self, word: str, context: str = "", cefr_level: str = "B1"
    ) -> WordExplanation:
        cleaned = word.strip().lower()
        key = cache_key(
            "word", "v4", cefr_level, cleaned, context.strip(), self.provider.signature
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
                    f"Explain: {word}",
                    WordLookup,
                    max_tokens=400,
                )
                if raw:
                    lookup = WordLookup.model_validate(raw)
                    return _expand_lookup(lookup, word, cefr_level), True
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
