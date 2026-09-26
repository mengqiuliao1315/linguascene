"""划词解析 Agent：划一个词或短语，实时给出释义与一条可采纳的笔记。

结果进缓存（同一个词 + 同一句只调一次模型）。模型没调通时不缓存，
避免一次失败被钉死成一周的空释义。
"""

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
        # 传入用户自己的 provider；不传则回落到环境变量兜底实例
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def analyze(
        self, text: str, sentence: str = "", cefr_level: str = "B1"
    ) -> WordPhraseAnalysis:
        return self.analyze_with_status(text, sentence, cefr_level)[0]

    def analyze_with_status(
        self, text: str, sentence: str = "", cefr_level: str = "B1"
    ) -> tuple[WordPhraseAnalysis, bool]:
        """返回 (解析, 是否权威可缓存)。语义与 SentenceAgent 一致。"""
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
                    # 模型偶尔会把 text 留空，补上用户实际划的内容
                    if not result.text:
                        result.text = text
                    return result, True
            except (AIProviderError, ValueError) as exc:
                logger.warning("WordPhraseAgent 模型调用失败，降级到词表：%s", exc)
                # 模型在但调用失败：兜底结果不可信，不缓存
                return self._offline_analyze(text, sentence, cefr_level), False

        return self._offline_analyze(text, sentence, cefr_level), True

    def _offline_analyze(
        self, text: str, sentence: str, cefr_level: str
    ) -> WordPhraseAnalysis:
        """离线：单个词查分级词表，短语不猜释义。

        划短语时规则引擎给不出可靠释义，宁可留空让用户自己写笔记，
        也不编一个看起来像模像样的中文解释。
        """
        # 延迟导入：reading_service 依赖 agents，模块级导入会成环
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
