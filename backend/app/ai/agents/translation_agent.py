"""翻译 Agent：把英文整句译成中文。

刻意只用单字段 Schema、单条规则。对话里的「翻译」按钮原先复用了句子分析
（主干、搭配、语法、近义表达一共七个字段），模型要把整包 JSON 写完才返回，
所以点一下要等十秒上下。翻译本身只需要一句话，单独开一条最轻的链路即可。
"""

import logging

from app.ai import rule_engine
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import TranslationOut
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)

# 一句话的翻译不会变，缓存留久一点；键里带 provider signature，
# 换模型/换 Key 后旧结果自动失效。
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
                # 待译文本走 user prompt，system prompt 保持静态，便于服务端复用前缀缓存
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

        # 离线兜底：内置的句式翻译表，翻不出来就返回空串，
        # 由前端显示「暂不支持」而不是编一句假的。
        return rule_engine.translate_sentence(cleaned)
