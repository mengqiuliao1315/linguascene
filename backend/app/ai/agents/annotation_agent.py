"""建议标注 Agent：读一句原文，挑出值得标注的词/搭配/结构。

只给建议、不落库。模型失败时**不写缓存**——否则一次 401 会让"建议"整周为空。
离线兜底只按分级词表挑超纲词，不猜搭配和语法：没有词表就无从判断，
宁可给 0-3 个可靠建议，也不要编一堆看起来像模像样的假标注。
"""

import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import AnnotationSuggestions, SuggestedSpan
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)

_ALLOWED_COLORS = {"blue", "green", "amber", "violet"}
_MAX_SPANS = 4


class AnnotationAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        # 传入用户自己的 provider；不传则回落到环境变量兜底实例
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def suggest_with_status(
        self, sentence: str, cefr_level: str = "B1"
    ) -> tuple[AnnotationSuggestions, bool]:
        """返回 (建议, 是否由模型产出)。调用方据此决定要不要提示用户。"""
        cleaned = " ".join(sentence.split())
        if not cleaned:
            return AnnotationSuggestions(), True

        key = cache_key(
            "annotation", "v1", cefr_level, cleaned, self.provider.signature
        )
        cached = self.cache.get(key)
        if cached:
            return AnnotationSuggestions.model_validate(cached), True

        result, from_model = self._suggest_uncached(cleaned, cefr_level)
        if from_model:
            self.cache.set(key, result.model_dump(), ttl_seconds=604800)
        return result, from_model

    def _suggest_uncached(
        self, sentence: str, cefr_level: str
    ) -> tuple[AnnotationSuggestions, bool]:
        if not self.provider.is_mock:
            try:
                system = render_prompt(
                    "annotation_agent",
                    sentence=sentence,
                    cefr_level=cefr_level,
                    max_suggestions=_MAX_SPANS,
                )
                raw = self.provider.complete_json(
                    system, f"Sentence: {sentence}", AnnotationSuggestions
                )
                if raw:
                    parsed = AnnotationSuggestions.model_validate(raw)
                    return self._validate(parsed, sentence), True
            except (AIProviderError, ValueError) as exc:
                logger.warning("AnnotationAgent 模型调用失败，降级到词表：%s", exc)
                # 模型在但调用失败：兜底结果不可信，不缓存
                return self._offline_suggest(sentence, cefr_level), False

        # 没配模型：离线规则引擎就是正式产出
        return self._offline_suggest(sentence, cefr_level), True

    def _validate(
        self, suggestions: AnnotationSuggestions, sentence: str
    ) -> AnnotationSuggestions:
        """丢掉找不到原文的 span，并把 text 归一成原文里的实际写法。

        模型时常顺手把 "don't" 写成 "do not"、把句首大写改小写，这类 span
        一旦放进前端就会指到错误位置，所以宁可丢掉。
        """
        kept: list[SuggestedSpan] = []
        lowered = sentence.lower()
        for span in suggestions.spans:
            text = span.text.strip()
            if not text or len(text) > 200:
                continue
            index = lowered.find(text.lower())
            if index < 0:
                continue
            # 整句本身不算标注建议
            if index == 0 and len(text) >= len(sentence):
                continue
            color = span.color if span.color in _ALLOWED_COLORS else "blue"
            kept.append(
                SuggestedSpan(
                    text=sentence[index : index + len(text)],
                    color=color,
                    reason=span.reason.strip(),
                )
            )
            if len(kept) >= _MAX_SPANS:
                break
        return AnnotationSuggestions(spans=kept)

    def _offline_suggest(
        self, sentence: str, cefr_level: str
    ) -> AnnotationSuggestions:
        """离线：只按分级词表挑超纲词，标成生词色。"""
        vocab = rule_engine.extract_vocabulary(sentence, cefr_level, limit=_MAX_SPANS)
        spans = [
            SuggestedSpan(
                text=item["word"],
                color="blue",
                reason=f"{item['level']} 级别词，可以顺手记一下",
            )
            for item in vocab
        ]
        return AnnotationSuggestions(spans=spans)
