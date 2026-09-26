"""逐句分析批大小/并发的自适应调节。

用户不知道自己接的模型限流多少、延迟多少，没法手填参数。这里让系统
自己摸：默认一组保守值，运行时按反馈升降，跨请求记住，重启后重来。

反馈信号：
- 截断（模型一次返回的条数对不齐）→ 批太大撑爆输出 token 上限，收批大小。
- 限流（429）→ 并发或批量把服务商打急了，收并发和批大小。
- 超时 → 链路太慢，收并发避免排队堆积。
- 一切顺利且累积够多 → 缓慢探测更大的批，长文也能更快。

线程安全：多请求并发跑逐句分析时会同时读写，用锁保护。进程级单例。
"""

import threading

DEFAULT_BATCH = 4
DEFAULT_WORKERS = 4
MIN_BATCH = 2
MAX_BATCH = 8
MIN_WORKERS = 2
MAX_WORKERS = 6

# 连续成功多少次才探测加大一档：太频繁会把刚稳下来的参数又推到不稳。
SUCCESS_BEFORE_PROBE = 8


class AdaptiveBatchSizer:
    """进程级自适应器：按运行时反馈升降 (batch_size, workers)。"""

    def __init__(self) -> None:
        self._batch = DEFAULT_BATCH
        self._workers = DEFAULT_WORKERS
        self._success_streak = 0
        self._lock = threading.Lock()

    def current(self) -> tuple[int, int]:
        """当前推荐的 (批大小, 并发度)。"""
        with self._lock:
            return self._batch, self._workers

    def note_success(self, batch_size: int) -> None:
        """一批顺利跑完。批量大小正好等于当前推荐值时才计入"稳"，避免
        用历史大值冒进。累积够多再探测加大一档，且不超上限。"""
        with self._lock:
            if batch_size != self._batch:
                # 不是按当前推荐值跑的（比如手动指定），不参与探测
                return
            self._success_streak += 1
            if (
                self._success_streak >= SUCCESS_BEFORE_PROBE
                and self._batch < MAX_BATCH
            ):
                self._batch += 1
                self._success_streak = 0

    def note_truncation(self) -> None:
        """返回条数对不齐：批太大撑爆 token 上限，立刻收一档。"""
        with self._lock:
            self._batch = max(MIN_BATCH, self._batch - 1)
            self._success_streak = 0

    def note_rate_limit(self) -> None:
        """触发服务商限流：并发和批大小一起收，给服务商喘口气。"""
        with self._lock:
            self._workers = max(MIN_WORKERS, self._workers - 1)
            self._batch = max(MIN_BATCH, self._batch - 1)
            self._success_streak = 0

    def note_timeout(self) -> None:
        """调用超时：链路慢，收并发避免请求在客户端排队堆积。"""
        with self._lock:
            self._workers = max(MIN_WORKERS, self._workers - 1)
            self._success_streak = 0

    def note_failure(self) -> None:
        """通用失败（鉴权、地址错误等）：不归咎批大小/并发，只重置探测计数，
        避免确定性失败被当成"参数不稳"反复降。"""
        with self._lock:
            self._success_streak = 0

    # 便于测试
    def _reset(self) -> None:
        with self._lock:
            self._batch = DEFAULT_BATCH
            self._workers = DEFAULT_WORKERS
            self._success_streak = 0


_tuner: AdaptiveBatchSizer | None = None
_tuner_lock = threading.Lock()


def get_batch_tuner() -> AdaptiveBatchSizer:
    """进程级单例：跨请求共享同一份自适应参数。"""
    global _tuner
    if _tuner is None:
        with _tuner_lock:
            if _tuner is None:
                _tuner = AdaptiveBatchSizer()
    return _tuner


def classify_error(exc: Exception) -> str:
    """把模型调用异常归类成自适应器能用的信号名。

    provider 抛的 AIProviderError 文本是"模型调用失败：{原始异常}"，原始异常
    里 httpx 的状态码错误会带 "429"、超时会带 "timed out"，据此识别。
    """
    raw = str(exc)
    lowered = raw.lower()
    if "429" in raw or "rate limit" in lowered or "限流" in raw:
        return "rate_limit"
    if "timeout" in lowered or "timed out" in lowered or "超时" in raw:
        return "timeout"
    return "failure"
