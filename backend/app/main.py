import logging
import threading

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.routes import (
    admin,
    ai,
    ai_settings,
    ai_shares,
    articles,
    audio,
    auth,
    content,
    conversations,
    dashboard,
    forum,
    friends,
    gamification,
    pet,
    quests,
    reading,
    scenarios,
    scenario_admin,
    users,
    vocabulary,
    wordbook,
)
from app.core.config import settings
from app.core.cache import get_cache
from app.core.database import SessionLocal, engine
from app.core.db_migrate import migrate_legacy_ai_config
from app.core.schema_sync import apply_schema
from app.core.storage import get_storage
from app.services import conversation_service
from app.models.learning import Scenario
from app.services import audio_service, local_asr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    description="场景化英语学习平台 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """统一错误响应，避免把堆栈暴露给前端。"""
    logger.exception("未处理的异常：%s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


@app.on_event("startup")
def on_startup() -> None:
    if settings.auto_create_tables:
        # 开发便捷路径；生产环境应使用 `alembic upgrade head`
        apply_schema(engine)
        migrate_legacy_ai_config(engine)
        logger.info("数据库表已就绪（%s）", settings.database_url)

    get_cache()
    get_storage()
    prewarm_speech()
    # 本地语音识别模型：第一次用要下载（几十秒），放到后台先加载好
    local_asr.warm_up()


def prewarm_speech() -> None:
    """把常驻的固定台词先合成好，用户点开对话就能直接出声。

    场景开场白与自由对话的开场句都是内置文本、全站共用同一份音频：启动时
    预热一次，之后每次朗读都是磁盘缓存命中（毫秒级），不必再等 1~2 秒的
    「建连 + 合成」。跑在后台线程里，不拖慢启动。
    """
    if not settings.speech_prewarm or not audio_service.tts_available():
        return

    def run() -> None:
        try:
            audio_service.warm_up()
            db = SessionLocal()
            try:
                lines = list(
                    db.execute(
                        select(Scenario.opening_line).where(
                            Scenario.is_published.is_(True)
                        )
                    ).scalars()
                )
            finally:
                db.close()
            lines.append(conversation_service.FREE_TALK_OPENING)
            audio_service.prewarm_lines(lines)
            logger.info("开场白语音预热已提交（%d 句）", len(lines))
        except Exception as exc:  # noqa: BLE001 - 预热失败不影响任何功能
            logger.info("开场白语音预热失败：%s", exc)

    threading.Thread(target=run, name="tts-prewarm-openings", daemon=True).start()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.env}


for router in (
    auth.router,
    users.router,
    admin.router,
    scenario_admin.router,
    dashboard.router,
    scenarios.router,
    conversations.router,
    audio.router,
    articles.router,
    content.router,
    reading.router,
    vocabulary.router,
    wordbook.router,
    gamification.router,
    pet.router,
    quests.router,
    friends.router,
    forum.router,
    ai.router,
    ai_settings.router,
    ai_shares.router,
):
    app.include_router(router)
