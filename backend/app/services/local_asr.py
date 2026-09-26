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


def available() -> bool:
    return _IMPORT_ERROR is None and settings.local_asr


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


def transcribe(audio: bytes, *, filename: str = "speech.webm") -> str | None:
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
                beam_size=1,
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
