from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parents[2] / "storage" / "whisper"

try:
    from faster_whisper import WhisperModel

    _IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - 取决于部署环境
    _IMPORT_ERROR = str(exc)
    WhisperModel = None  # type: ignore[assignment]

_model = None
_model_lock = threading.Lock()
_run_lock = threading.Lock()

# 给模型一段「标准英文」的上下文：whisper 会照着这个风格输出，
# 于是结果自带大小写和标点，而不是一长串小写单词。
# 这里只管风格，不写任何具体场景的词汇——场景词由调用方用 hotwords 传进来，
# 否则换到「机场值机」还带着咖啡店的口音偏好，反而更容易听错。
_INITIAL_PROMPT = "Hello! How can I help you today? Yes, please. Thank you very much."


def unavailable_reason() -> str:
    """本地识别为什么用不了——直接拿去告诉用户，省得猜。"""
    if _IMPORT_ERROR is not None:
        return "服务端没装 faster-whisper（pip install -r requirements.txt）"
    if not settings.local_asr:
        return "服务端把 LOCAL_ASR 关掉了"
    return ""


def available() -> bool:
    return unavailable_reason() == ""


def model_name() -> str:
    return settings.local_asr_model


def _load():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("正在加载本地识别模型 %s（首次需下载）…", model_name())
        _model = WhisperModel(
            model_name(),
            device="cpu",
            compute_type="int8",
            download_root=str(_CACHE_DIR),
        )
        logger.info("本地识别模型已就绪：%s", model_name())
    return _model


def warm_up() -> None:
    if not available():
        return

    def run() -> None:
        try:
            _load()
        except Exception as exc:  # noqa: BLE001 - 加载失败只是没有本地识别
            logger.info("本地识别模型加载失败：%s", exc)

    threading.Thread(target=run, name="local-asr-warmup", daemon=True).start()


def transcribe(audio: bytes, *, filename: str = "speech.webm", hotwords: str = "") -> str | None:
    if not available() or not audio:
        return None

    try:
        model = _load()
    except Exception as exc:  # noqa: BLE001 - 下载/加载失败，让调用方回退
        logger.warning("本地识别模型不可用：%s", exc)
        return None

    suffix = Path(filename).suffix or ".webm"
    tmp = _CACHE_DIR / f"upload-{threading.get_ident()}-{id(audio)}{suffix}"
    try:
        tmp.write_bytes(audio)
        with _run_lock:
            segments, _info = model.transcribe(
                str(tmp),
                language="en",
                # beam search 比贪心更能挑出带标点的写法；配合 initial_prompt
                # 一起保证「I'd like a latte, please.」这种大小写和标点。
                beam_size=5,
                initial_prompt=_INITIAL_PROMPT,
                # 场景自带的重点句式和词汇：whisper 会把它们当成上下文，
                # 优先往这些词上靠。学生说的基本就是这个场景里的词，明显更认得住。
                hotwords=hotwords or None,
                # 每段都是几秒的短录音，不需要跨段复用上下文（反而容易串词）。
                condition_on_previous_text=False,
                vad_filter=True,
                without_timestamps=True,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as exc:  # noqa: BLE001 - 解码失败等，交给上层回退
        logger.warning("本地识别失败：%s", exc)
        return None
    finally:
        tmp.unlink(missing_ok=True)

    return text
