"""文章分析 Agent：把任意英语材料转成学习材料。"""

import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import ArticleAnalysisOut
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)

MAX_ANALYSIS_CHARS = 6000


class ArticleAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def analyze(
        self, content: str, cefr_level: str = "B1", cache_token: str = ""
    ) -> ArticleAnalysisOut:
        cleaned = content.strip()
        key = cache_key(
            "article",
            cefr_level,
            cache_token or str(len(cleaned)),
            self.provider.signature,
        )
        cached = self.cache.get(key)
        if cached:
            return ArticleAnalysisOut.model_validate(cached)

        result = self._analyze_uncached(cleaned, cefr_level)
        self.cache.set(key, result.model_dump(), ttl_seconds=604800)
        return result

    def _analyze_uncached(self, content: str, cefr_level: str) -> ArticleAnalysisOut:
        # 长文章先截断，避免一次塞入超长上下文；生产环境应改为分块摘要再分析
        truncated = content[:MAX_ANALYSIS_CHARS]

        if not self.provider.is_mock:
            try:
                system = render_prompt(
                    "article_agent", cefr_level=cefr_level, content=truncated
                )
                raw = self.provider.complete_json(
                    system, "Analyze this material.", ArticleAnalysisOut
                )
                if raw:
                    return ArticleAnalysisOut.model_validate(raw)
            except (AIProviderError, ValueError) as exc:
                logger.warning("ArticleAgent 模型调用失败，降级到规则引擎：%s", exc)

        return self._offline_analyze(truncated, cefr_level)

    def _offline_analyze(self, content: str, cefr_level: str) -> ArticleAnalysisOut:
        """离线：词汇按分级词表提取，句子与问题用可复现的文本规则生成。"""
        vocab_hits = rule_engine.extract_vocabulary(content, cefr_level, limit=8)

        sentences = [
            s.strip()
            for s in __import__("re").split(r"(?<=[.!?])\s+", content)
            if len(s.strip()) > 20
        ]
        reading_questions = [
            "What is the main idea of this text?",
            "Which detail best supports the main idea?",
            "What is the author's attitude toward the topic?",
        ]

        return ArticleAnalysisOut(
            summary=_first_sentences(content, 2),
            level=cefr_level,
            keywords=[
                {
                    "word": item["word"],
                    "meaning": item["meaning"],
                    "example": _sentence_containing(sentences, item["word"]),
                }
                for item in vocab_hits
            ],
            phrases=[],
            grammar_points=[],
            reading_questions=reading_questions,
            speaking_questions=[
                "Summarize this text in your own words in 30 seconds.",
                "Do you agree with the author? Why or why not?",
            ],
            writing_task="Write a short paragraph responding to the main argument of this text.",
        )


def _first_sentences(text: str, count: int) -> str:
    import re

    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:count]).strip()


def _sentence_containing(sentences: list[str], word: str) -> str:
    for sentence in sentences:
        if word.lower() in sentence.lower():
            return sentence
    return ""
