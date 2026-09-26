from __future__ import annotations

import logging
import threading

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse

from app.ai.provider import (
    AIProviderError,
    detect_stt_model,
    stt_status,
)
from app.api.deps import get_current_user, get_user_provider
from app.services import audio_service, local_asr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audio", tags=["audio"])

MAX_TRANSCRIBE_BYTES = 12 * 1024 * 1024


@router.get("/capability")
def audio_capability() -> dict:
    """朗读能力探测：装了 edge-tts 就能合成整句语音。

    前端页面一加载就会打这个接口，正好借机预热合成连接池：
    用户第一次点喇叭时连接已经是热的，不用再付 1s 上下的握手钱。
    预热是后台异步的，这里立即返回、不拖慢探测。
    """
    available = audio_service.tts_available()
    if available:
        audio_service.warm_up()
    return {"tts": available}


@router.get("/tts")
def text_to_speech(
    text: str = Query(min_length=1, max_length=1200),
    lang: str = Query(default="en-US"),
):
    """把任意英文句子合成为语音。

    浏览器内置的 speechSynthesis 在内嵌 webview 里往往只装了中文语音，
    读英文会静默失败（点了没声音）。这里用 edge-tts 合成后返回 mp3，
    前端拿不到音频时再回退到浏览器朗读。

    和其他音频接口一样不校验登录：<audio src> 不会带 Authorization 头。
    """
    path = audio_service.synthesize_text(text, lang)
    if path is None:
        raise HTTPException(status_code=404, detail="暂时无法合成语音，请使用浏览器朗读")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=path.name,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


ENGINE_MODEL = "model"
ENGINE_LOCAL = "local"


def _local_option() -> dict | None:
    if not local_asr.available():
        return None
    return {
        "id": ENGINE_LOCAL,
        "label": "本地识别",
        "detail": f"在这台服务器上识别（whisper {local_asr.model_name()}），免费、不需要 Key",
    }


@router.get("/stt")
def stt_capability(
    user=Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> dict:
    """语音输入能力探测：用户自己的模型能不能转写、还有哪些备选通道。

    用户配置里只有对话模型名，认不认转写要试一次才知道。探测可能要好几秒，
    所以丢到后台线程，本次照常返回「可用」——用户真正按麦克风时通常已经探好了，
    探出来不支持就由前端弹窗。

    `engine` 是默认该用哪条：只用用户自己配的模型（支持转写时），不支持就留空，
    由前端弹窗让用户选备选通道，而不是替他换。
    """
    status = stt_status(provider)
    if status["available"] and status["reason"] == "":
        threading.Thread(
            target=_probe_stt_model,
            args=(provider,),
            name="stt-detect",
            daemon=True,
        ).start()

    local = _local_option()
    status["engines"] = [local] if local else []
    status["engine"] = ENGINE_MODEL if status["available"] else ""
    status["local_model"] = local_asr.model_name() if local_asr.available() else ""
    return status


def _probe_stt_model(provider) -> None:
    try:
        detect_stt_model(provider)
    except Exception as exc:  # noqa: BLE001 - 探测失败不影响任何功能
        logger.info("语音转写后台探测失败：%s", exc)


@router.post("/transcribe")
def transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="en"),
    engine: str = Form(default=ENGINE_MODEL),
    user=Depends(get_current_user),
    provider=Depends(get_user_provider),
) -> dict:
    """把一段录音转成英文文本。

    前端按停顿把说话切段，每段上传一次，所以这里的音频都很短（几秒）。

    engine 说清这一段的录音交给谁识别：

    * `model`（默认）：用户自己在 AI 模型页配的那家。识别不了就如实报错，
      **不会**偷偷换别的通道——换通道要用户自己同意。
    * `local`：服务端本地识别（开源模型跑在这台机器上，不连任何 API、不要 Key）。

    两种情况下前端拿到 503 会弹窗让用户选通道；502 是这次没成（超时、限流、
    Key 失效），提示重试即可。
    """
    audio = file.file.read(MAX_TRANSCRIBE_BYTES + 1)
    if not audio:
        raise HTTPException(status_code=400, detail="没有收到音频")
    if len(audio) > MAX_TRANSCRIBE_BYTES:
        raise HTTPException(status_code=413, detail="录音太长了，请分段说")

    filename = file.filename or "speech.webm"

    if engine == ENGINE_LOCAL:
        if not local_asr.available():
            raise HTTPException(status_code=503, detail="这台服务器没有启用本地识别")
        text = local_asr.transcribe(audio, filename=filename)
        if not text:
            raise HTTPException(status_code=502, detail="本地识别没听出内容，请再说一遍")
        return {"text": text, "engine": ENGINE_LOCAL}

    try:
        text = provider.transcribe(
            audio,
            filename=filename,
            content_type=file.content_type or "audio/webm",
            language=language,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if text is None:
        raise HTTPException(
            status_code=503,
            detail="你在 AI 模型里配置的这个模型不支持语音输入，请换一个支持转写的模型，或改用其它识别通道",
        )
    return {"text": text, "engine": ENGINE_MODEL}
