import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import TranslationOut
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)

TRANSLATION_TTL_SECONDS = 604800


class TranslationAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def translate(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""

        key = cache_key("translate", "v1", cleaned, self.provider.signature)
        cached = self.cache.get(key)
        if cached is not None:
            return str(cached.get("translation", ""))

        if not self.provider.is_mock:
            try:
                system = render_prompt("translate_agent")
                raw = self.provider.complete_json_fast(
                    system, f"Text: {cleaned}", TranslationOut, max_tokens=400
                )
                if raw:
                    result = TranslationOut.model_validate(raw)
                    if result.translation.strip():
                        self.cache.set(
                            key, result.model_dump(), ttl_seconds=TRANSLATION_TTL_SECONDS
                        )
                        return result.translation.strip()
            except (AIProviderError, ValueError) as exc:
                logger.warning("TranslationAgent 模型调用失败，降级到规则引擎：%s", exc)

        return rule_engine.translate_sentence(cleaned)
