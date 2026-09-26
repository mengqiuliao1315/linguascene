import logging
import re

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import WordPhraseAnalysis
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'-]*$")


class WordPhraseAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def analyze(
        self, text: str, sentence: str = "", cefr_level: str = "B1"
    ) -> WordPhraseAnalysis:
        return self.analyze_with_status(text, sentence, cefr_level)[0]

    def analyze_with_status(
        self, text: str, sentence: str = "", cefr_level: str = "B1"
    ) -> tuple[WordPhraseAnalysis, bool]:
        cleaned = " ".join(text.split())
        key = cache_key(
            "wordphrase", "v1", cefr_level, cleaned, sentence.strip(),
            self.provider.signature,
        )
        cached = self.cache.get(key)
        if cached:
            return WordPhraseAnalysis.model_validate(cached), True

        result, from_model = self._analyze_uncached(cleaned, sentence, cefr_level)
        if from_model:
            self.cache.set(key, result.model_dump(), ttl_seconds=604800)
        return result, from_model

    def _analyze_uncached(
        self, text: str, sentence: str, cefr_level: str
    ) -> tuple[WordPhraseAnalysis, bool]:
        if not self.provider.is_mock:
            try:
                system = render_prompt(
                    "word_phrase_agent",
                    text=text,
                    sentence=sentence,
                    cefr_level=cefr_level,
                )
                raw = self.provider.complete_json_fast(
                    system, f"Explain: {text}", WordPhraseAnalysis, max_tokens=400
                )
                if raw:
                    result = WordPhraseAnalysis.model_validate(raw)
                    if not result.text:
                        result.text = text
                    return result, True
            except (AIProviderError, ValueError) as exc:
                logger.warning("WordPhraseAgent 模型调用失败，降级到词表：%s", exc)
                return self._offline_analyze(text, sentence, cefr_level), False

        return self._offline_analyze(text, sentence, cefr_level), True

    def _offline_analyze(
        self, text: str, sentence: str, cefr_level: str
    ) -> WordPhraseAnalysis:
        from app.services.reading_service import lemmatize

        lowered = text.strip().lower()
        if not _WORD_RE.match(lowered):
            return WordPhraseAnalysis(
                kind="phrase", text=text, lemma=text, example=sentence.strip()
            )

        meaning = ""
        for lexicon in rule_engine.VOCAB_BY_LEVEL.values():
            if lowered in lexicon:
                meaning = lexicon[lowered]
                break

        return WordPhraseAnalysis(
            kind="word",
            text=text,
            lemma=lemmatize(lowered),
            meaning=meaning,
            example=sentence.strip(),
        )
