"""本地语音识别（不需要任何 API Key，也不花钱）。

场景：这是开源站点，不给用户提供模型 API；用户自己没接语音模型、或者接的那把
Key 不支持转写时，麦克风就没有别的通道可用了（浏览器自带识别在内嵌 webview 里
连不上浏览器厂商的识别服务，已按产品要求删除）。这时候唯一还能用的就是
「服务端自己认」——本机跑一个小 Whisper，不连任何第三方接口、不产生任何费用。

装了 `faster-whisper` 就自动启用（和 edge-tts 一样是可选依赖），没装则整个模块
静默失效，`available()` 返回 False，调用方回退到原来的链路。

几个实测过的取舍（本机 CPU，3~5 秒的英文短句）：

| 模型 | 体积 | 一句耗时 | 认得出 "oat milk" 吗 |
| --- | --- | --- | --- |
| tiny.en | ~75MB | 0.5s | 否（听成 without） |
| base.en | ~145MB | 1.1s | 否 |
| small.en | ~490MB | 2.6s | 是 |

默认给 small.en：base.en 快半秒，但把 "oat milk" 听成别的词，场景对话里
这种错比多等一秒更伤。内存吃紧的部署把 `LOCAL_ASR_MODEL` 改回 `base.en`。

模型文件由 faster-whisper 自己从 HuggingFace 下载到 `storage/whisper`，只需
下载一次；之后完全离线可用。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# 模型缓存目录：放 storage 下，和音频缓存做邻居，部署时一起持久化
_CACHE_DIR = Path(__file__).resolve().parents[2] / "storage" / "whisper"

try:  # 可选依赖：没装就整条链路降级，导入本身不能失败
    from faster_whisper import WhisperModel

    _IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - 取决于部署环境
    _IMPORT_ERROR = str(exc)
    WhisperModel = None  # type: ignore[assignment]

_model = None
_model_lock = threading.Lock()
# 一次只跑一条转写：CPU 上并发跑只会互相抢核，谁都不快
_run_lock = threading.Lock()


def available() -> bool:
    """本机能不能做语音识别：装了 faster-whisper 且没被配置关掉。"""
    return _IMPORT_ERROR is None and settings.local_asr


def model_name() -> str:
    return settings.local_asr_model


def _load():
    """惰性加载模型（首次会下载，几十秒），加载成功后常驻内存。"""
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
    """后台把模型加载好，用户第一次按麦克风就不用等那几十秒。"""
    if not available():
        return

    def run() -> None:
        try:
            _load()
        except Exception as exc:  # noqa: BLE001 - 加载失败只是没有本地识别
            logger.info("本地识别模型加载失败：%s", exc)

    threading.Thread(target=run, name="local-asr-warmup", daemon=True).start()


def transcribe(audio: bytes, *, filename: str = "speech.webm") -> str | None:
    """把一段录音转成英文文本；本地识别不可用或失败时返回 None。

    识别结果自带标点与大小写（whisper 系的能力），所以调用方不用再整形。
    """
    if not available() or not audio:
        return None

    try:
        model = _load()
    except Exception as exc:  # noqa: BLE001 - 下载/加载失败，让调用方回退
        logger.warning("本地识别模型不可用：%s", exc)
        return None

    suffix = Path(filename).suffix or ".webm"
    # 并发请求不能共用同一个临时文件，否则后到的会把先到的音频覆盖掉
    tmp = _CACHE_DIR / f"upload-{threading.get_ident()}-{id(audio)}{suffix}"
    try:
        tmp.write_bytes(audio)
        with _run_lock:
            segments, _info = model.transcribe(
                str(tmp),
                language="en",
                beam_size=1,
                vad_filter=True,
                # 不要时间戳：输入框只需要文本，省掉无用的分段元数据。
                without_timestamps=True,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as exc:  # noqa: BLE001 - 解码失败等，交给上层回退
        logger.warning("本地识别失败：%s", exc)
        return None
    finally:
        tmp.unlink(missing_ok=True)

    return text
