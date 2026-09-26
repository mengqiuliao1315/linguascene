import threading

DEFAULT_BATCH = 4
DEFAULT_WORKERS = 4
MIN_BATCH = 2
MAX_BATCH = 8
MIN_WORKERS = 2
MAX_WORKERS = 6

SUCCESS_BEFORE_PROBE = 8


class AdaptiveBatchSizer:

    def __init__(self) -> None:
        self._batch = DEFAULT_BATCH
        self._workers = DEFAULT_WORKERS
        self._success_streak = 0
        self._lock = threading.Lock()

    def current(self) -> tuple[int, int]:
        with self._lock:
            return self._batch, self._workers

    def note_success(self, batch_size: int) -> None:
        with self._lock:
            if batch_size != self._batch:
                return
            self._success_streak += 1
            if (
                self._success_streak >= SUCCESS_BEFORE_PROBE
                and self._batch < MAX_BATCH
            ):
                self._batch += 1
                self._success_streak = 0

    def note_truncation(self) -> None:
        with self._lock:
            self._batch = max(MIN_BATCH, self._batch - 1)
            self._success_streak = 0

    def note_rate_limit(self) -> None:
        with self._lock:
            self._workers = max(MIN_WORKERS, self._workers - 1)
            self._batch = max(MIN_BATCH, self._batch - 1)
            self._success_streak = 0

    def note_timeout(self) -> None:
        with self._lock:
            self._workers = max(MIN_WORKERS, self._workers - 1)
            self._success_streak = 0

    def note_failure(self) -> None:
        with self._lock:
            self._success_streak = 0

    def _reset(self) -> None:
        with self._lock:
            self._batch = DEFAULT_BATCH
            self._workers = DEFAULT_WORKERS
            self._success_streak = 0


_tuner: AdaptiveBatchSizer | None = None
_tuner_lock = threading.Lock()


def get_batch_tuner() -> AdaptiveBatchSizer:
    global _tuner
    if _tuner is None:
        with _tuner_lock:
            if _tuner is None:
                _tuner = AdaptiveBatchSizer()
    return _tuner


def classify_error(exc: Exception) -> str:
    raw = str(exc)
    lowered = raw.lower()
    if "429" in raw or "rate limit" in lowered or "限流" in raw:
        return "rate_limit"
    if "timeout" in lowered or "timed out" in lowered or "超时" in raw:
        return "timeout"
    return "failure"
