import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import CorrectionOut
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)


class CorrectionAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def analyze(self, text: str, cefr_level: str = "B1") -> dict | None:
        cleaned = text.strip()
        if not cleaned:
            return None

        key = cache_key("correction", cefr_level, cleaned, self.provider.signature)
        cached = self.cache.get(key)
        if cached is not None:
            return cached or None

        result = self._analyze_uncached(cleaned, cefr_level)
        self.cache.set(key, result or {}, ttl_seconds=86400)
        return result

    def _analyze_uncached(self, text: str, cefr_level: str) -> dict | None:
        if not self.provider.is_mock:
            try:
                system = render_prompt("correction_agent", cefr_level=cefr_level)
                raw = self.provider.complete_json(
                    system, f"Sentence: {text}", CorrectionOut
                )
                if raw:
                    parsed = CorrectionOut.model_validate(raw)
                    return parsed.model_dump() if parsed.has_error else None
            except (AIProviderError, ValueError) as exc:
                logger.warning("CorrectionAgent 模型调用失败，降级到规则引擎：%s", exc)

        return rule_engine.detect_correction(text)
