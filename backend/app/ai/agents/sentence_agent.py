"""句子分析 Agent：拆主干、挑重点词与固定搭配、点出语法。"""

import logging
import re

from app.ai import rule_engine
from app.ai.batch_tuner import classify_error, get_batch_tuner
from app.ai.prompts import render_prompt
from app.ai.provider import AIProvider, AIProviderError, get_provider
from app.ai.schemas import SentenceAnalysis, SentenceBatch
from app.core.cache import cache_key, get_cache

logger = logging.getLogger(__name__)

# 常见固定搭配模式，命中才提示，不硬凑
# 常见固定搭配。模式写成能容忍屈折变化的形式，
# 否则 "change the way" 匹配不到原文里的 "changed the way"。
COLLOCATION_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"\bplay(?:s|ed|ing)?\s+a\s+(?:important\s+|key\s+|major\s+|crucial\s+)?role\s+in\b",
        "play a role in",
        "在……中起作用",
    ),
    (r"\bthe\s+(?:\w+\s+){0,2}development\s+of\b", "the development of", "……的发展"),
    (r"\bchange(?:s|d|ing)?\s+the\s+way\b", "change the way", "改变……的方式"),
    (
        r"\b(?:be|is|are|was|were|been|being)\s+exposed\s+to\b",
        "be exposed to",
        "接触到……",
    ),
    (r"\badapt(?:s|ed|ing)?\s+to\b", "adapt to", "适应……"),
    (
        r"\bmak(?:e|es|ing)\s+(?:a\s+|an\s+|great\s+|good\s+)?(?:progress|decision|effort|sense)\b",
        "make progress / make a decision",
        "取得进步 / 做决定",
    ),
    (
        r"\bmade\s+(?:a\s+)?(?:progress|decision|effort)\b",
        "make progress / make a decision",
        "取得进步 / 做决定",
    ),
    (r"\btak(?:e|es|ing)\s+a\s+look\s+at\b", "take a look at", "看一看"),
    (r"\bin\s+terms\s+of\b", "in terms of", "就……而言"),
    (r"\bas\s+a\s+result\s+of\b", "as a result of", "由于……"),
    (r"\bpay(?:s|ing)?\s+attention\s+to\b", "pay attention to", "注意……"),
    (r"\bpaid\s+attention\s+to\b", "pay attention to", "注意……"),
    (r"\b(?:have|has|had)\s+access\s+to\b", "have access to", "有权使用……"),
    (r"\b(?:spend|spends|spent|spending)\s+time\s+(?:on|in)\b", "spend time on", "在……上花时间"),
    (r"\b(?:lead|leads|led|leading)\s+to\b", "lead to", "导致……"),
    (r"\b(?:contribute|contributes|contributed|contributing)\s+to\b", "contribute to", "促成……"),
    (r"\b(?:rely|relies|relied|relying)\s+on\b", "rely on", "依赖……"),
    (r"\b(?:focus|focuses|focused|focusing)\s+on\b", "focus on", "专注于……"),
]

GRAMMAR_HINTS: list[tuple[str, str, str, str]] = [
    (
        r"\bhas|have\b\s+\w+(?:ed|en)\b",
        "Present Perfect",
        "现在完成时：have/has + 过去分词",
        "The rapid development has changed the way students learn.",
    ),
    (
        r"\bwas|were\b\s+\w+(?:ed|en)\b",
        "Passive Voice (Past)",
        "一般过去时被动语态：was/were + 过去分词",
        "The report was published last week.",
    ),
    (
        r"\bwhich|who|that\b\s+\w+",
        "Relative Clause",
        "定语从句：关系代词引导修饰成分",
        "AI tools that adapt to learners are powerful.",
    ),
    (
        r"\b(?:will|would|can|could|may|might|must|should)\b",
        "Modal Verb",
        "情态动词：表达能力、可能、义务等语气",
        "This approach could improve retention.",
    ),
]


class SentenceAgent:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def analyze(
        self, sentence: str, cefr_level: str = "B1", context: str = ""
    ) -> SentenceAnalysis:
        return self.analyze_with_status(sentence, cefr_level, context)[0]

    def analyze_with_status(
        self, sentence: str, cefr_level: str = "B1", context: str = ""
    ) -> tuple[SentenceAnalysis, bool]:
        """返回 (讲解, 这份结果是否权威、可以缓存/落库)。

        离线模式下规则引擎就是正式产出，照常缓存；只有"配了真模型但这次
        没调通"的降级结果不能缓存——否则一次 401 或超时会被钉死成一周的
        正确输出，之后每次打开都命中空翻译，看起来就是 AI 链路一直不通。
        """
        cleaned = sentence.strip()
        # v2：离线模式开始返回整句中文，旧缓存里的空翻译必须失效
        key = cache_key("sentence", "v2", cefr_level, cleaned, self.provider.signature)
        cached = self.cache.get(key)
        if cached:
            return SentenceAnalysis.model_validate(cached), True

        result, from_model = self._analyze_uncached(cleaned, cefr_level, context)
        if from_model:
            self.cache.set(key, result.model_dump(), ttl_seconds=604800)
        return result, from_model

    def analyze_batch_with_status(
        self,
        sentences: list[str],
        cefr_level: str = "B1",
        context: str = "",
        *,
        fast: bool = False,
    ) -> list[tuple[SentenceAnalysis, bool]]:
        """一次模型调用分析多条句子，按入参顺序返回 (讲解, 是否权威)。

        单句一次往返时，长文几十句要排十几轮模型调用，逐句渐进返回虽好，
        全篇就绪仍要等几分钟。这里把若干句塞进一次调用：往返次数按批数缩，
        全篇就绪时间能压到原来的 1/N，首句就绪时间基本不变（一批里第一句
        跟单句差不多就绪）。

        容错与单句路径一致：
        - 命中缓存的句直接复用（缓存是按句的，跨批/跨次打开都复用）；
        - 没命中的若干句走一次批量调用；模型没配 / 调用失败 / 返回条数对不齐
          时降级成逐句调用，逐句内部仍走 _analyze_uncached 的兜底逻辑，
          不会因为一批里模型答歪了就整批空着。
        """
        if not sentences:
            return []

        results: list[tuple[SentenceAnalysis, bool] | None] = [None] * len(sentences)
        # 先吃缓存：缓存的句不必再进模型，批里只放真正要问模型的句。
        pending: list[tuple[int, str]] = []
        for index, sentence in enumerate(sentences):
            cleaned = sentence.strip()
            key = cache_key("sentence", "v2", cefr_level, cleaned, self.provider.signature)
            cached = self.cache.get(key)
            if cached:
                results[index] = (SentenceAnalysis.model_validate(cached), True)
            else:
                pending.append((index, cleaned))

        if pending:
            batch_resolved = self._analyze_batch_uncached(
                pending, cefr_level, context, fast=fast
            )
            for index, analysis, from_model in batch_resolved:
                results[index] = (analysis, from_model)

        # 类型检查帮不上忙：上面两条分支保证每个位置都填上了
        return [r for r in results if r is not None]  # type: ignore[misc]

    def _analyze_batch_uncached(
        self,
        pending: list[tuple[int, str]],
        cefr_level: str,
        context: str,
        *,
        fast: bool = False,
    ) -> list[tuple[int, SentenceAnalysis, bool]]:
        """批量调用模型分析未命中缓存的句子；失败则逐句兜底。

        返回 [(原句下标, 讲解, 是否权威)]，与 pending 一一对应。
        """
        # 只剩一句时走单句路径：批量化对单句没有收益，反而多一层包装。
        if len(pending) == 1 or self.provider.is_mock:
            resolved: list[tuple[int, SentenceAnalysis, bool]] = []
            for index, sentence in pending:
                analysis, from_model = self._analyze_uncached(
                    sentence, cefr_level, context, fast=fast
                )
                if from_model:
                    key = cache_key(
                        "sentence", "v2", cefr_level, sentence, self.provider.signature
                    )
                    self.cache.set(key, analysis.model_dump(), ttl_seconds=604800)
                resolved.append((index, analysis, from_model))
            return resolved

        numbered = "\n".join(f"{n}. {sentence}" for n, (_, sentence) in enumerate(pending, 1))
        try:
            system = render_prompt(
                "sentence_batch",
                count=len(pending),
                sentences=numbered,
                cefr_level=cefr_level,
            )
            # 批量输出成倍增长：单句默认上限不够，按句数线性放，并设个上限
            # 防止极端长文一次性申请超大窗口被服务商拒掉。
            base_tokens = getattr(self.provider, "max_tokens", 1500) or 1500
            batch_tokens = min(base_tokens * len(pending), 8000)
            raw = self.provider.complete_json(
                system,
                f"Analyze these {len(pending)} sentences.",
                SentenceBatch,
                max_tokens=batch_tokens,
            )
            items = (raw or {}).get("sentences") if isinstance(raw, dict) else None
            if items and len(items) == len(pending):
                resolved = []
                for (index, sentence), item in zip(pending, items):
                    analysis = SentenceAnalysis.model_validate(item)
                    key = cache_key(
                        "sentence", "v2", cefr_level, sentence, self.provider.signature
                    )
                    self.cache.set(key, analysis.model_dump(), ttl_seconds=604800)
                    resolved.append((index, analysis, True))
                # 这批跑顺了，喂给自适应器：累积够多会缓慢探测更大批，
                # 长文也能更快。
                get_batch_tuner().note_success(len(pending))
                return resolved
            # 条数对不齐：模型多半漏了几句或把多句并了，多半是输出 token
            # 上限撑不住这批。告诉自适应器收一档批大小，逐句兜底保证不空。
            get_batch_tuner().note_truncation()
            logger.warning(
                "批量逐句分析返回条数不符（期望 %d），降级逐句",
                len(pending),
            )
        except (AIProviderError, ValueError, TypeError) as exc:
            # 把失败归类喂给自适应器：限流收并发+批，超时收并发，其余不归咎参数
            getattr(get_batch_tuner(), f"note_{classify_error(exc)}")()
            logger.warning("批量逐句分析失败，降级为逐句调用：%s", exc)

        return self._analyze_pending_one_by_one(pending, cefr_level, context)

    def _analyze_pending_one_by_one(
        self,
        pending: list[tuple[int, str]],
        cefr_level: str,
        context: str,
    ) -> list[tuple[int, SentenceAnalysis, bool]]:
        resolved: list[tuple[int, SentenceAnalysis, bool]] = []
        for index, sentence in pending:
            analysis, from_model = self._analyze_uncached(sentence, cefr_level, context)
            if from_model:
                key = cache_key(
                    "sentence", "v2", cefr_level, sentence, self.provider.signature
                )
                self.cache.set(key, analysis.model_dump(), ttl_seconds=604800)
            resolved.append((index, analysis, from_model))
        return resolved

    def _analyze_uncached(
        self,
        sentence: str,
        cefr_level: str,
        context: str,
        *,
        fast: bool = False,
    ) -> tuple[SentenceAnalysis, bool]:
        if not self.provider.is_mock:
            try:
                system = render_prompt(
                    "sentence_agent", sentence=sentence, cefr_level=cefr_level
                )
                raw = (
                    self.provider.complete_json_fast
                    if fast
                    else self.provider.complete_json
                )(
                    system, f"Sentence: {sentence}", SentenceAnalysis
                )
                if raw:
                    return SentenceAnalysis.model_validate(raw), True
            except (AIProviderError, ValueError) as exc:
                logger.warning("SentenceAgent 模型调用失败，降级到规则引擎：%s", exc)
                # 模型在但调用失败：兜底结果不可信，不缓存
                return self._offline_analyze(sentence, cefr_level), False

        # 没配模型：离线规则引擎就是正式产出
        return self._offline_analyze(sentence, cefr_level), True

    def _offline_analyze(self, sentence: str, cefr_level: str) -> SentenceAnalysis:
        vocab = rule_engine.extract_vocabulary(sentence, cefr_level, limit=4)
        collocations = [
            {"phrase": phrase, "meaning": meaning, "example": sentence}
            for pattern, phrase, meaning in COLLOCATION_PATTERNS
            if re.search(pattern, sentence, re.IGNORECASE)
        ]
        grammar_points = [
            {"point": name, "explanation": explanation, "example": example}
            for pattern, name, explanation, example in GRAMMAR_HINTS
            if re.search(pattern, sentence, re.IGNORECASE)
        ]

        return SentenceAnalysis(
            sentence=sentence,
            chinese_meaning=rule_engine.translate_sentence(sentence),
            main_clause=self._extract_main_clause(sentence),
            structure="",
            vocabulary=[
                {"word": v["word"], "meaning": v["meaning"], "example": sentence}
                for v in vocab
            ],
            collocations=collocations,
            grammar_points=grammar_points,
            natural_alternative="",
            cefr_level=cefr_level,
        )

    def _extract_main_clause(self, sentence: str) -> str:
        """粗略主干：去掉从句与介词短语，保留主语-谓语-宾语骨架。"""
        text = re.sub(r",\s*(which|who|that)\b.*$", "", sentence, flags=re.IGNORECASE)
        text = re.sub(r"\b(which|who|that)\b.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(of|in|on|at|for|with|to)\b\s+\w+(\s+\w+)?", "", text, count=2)
        return re.sub(r"\s+", " ", text).strip(" ,.")
