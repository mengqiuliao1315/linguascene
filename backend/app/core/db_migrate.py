"""一次性迁移：把老库的 AI 配置搬到新结构。

老结构：
- 一人一条 ai_credentials，每个只有单个 model；
- ai_shares 里每个分享也只有单个 model（NOT NULL），且没有模型列表；
- 另有全站一条 platform_ai_config（平台免费模型，新结构里已取消）。

新结构：
- 一人多条 ai_provider_configs，每条带模型列表与当前选中的模型；
- ai_shares 带模型列表与默认模型，不再有单个 model 列。

只做数据搬运，重复执行安全；老表原样留着（不再被读写）。
"""

import json
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _has_table(inspector, name: str) -> bool:
    return name in set(inspector.get_table_names())


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _migrate_credentials(conn, inspector) -> int:
    """ai_credentials（单模型）→ ai_provider_configs（多模型）。"""
    if not (_has_table(inspector, "ai_credentials")
            and _has_table(inspector, "ai_provider_configs")):
        return 0
    if conn.execute(text("SELECT COUNT(*) FROM ai_provider_configs")).scalar_one():
        return 0  # 已经搬过

    rows = conn.execute(
        text(
            "SELECT user_id, model, base_url, api_key_encrypted, api_format, label "
            "FROM ai_credentials"
        )
    ).all()
    for row in rows:
        model = row.model or ""
        conn.execute(
            text(
                "INSERT INTO ai_provider_configs "
                "(user_id, name, base_url, api_key_encrypted, api_format, "
                " models, active_model, created_at, updated_at) "
                "VALUES (:user_id, :name, :base_url, :key, :fmt, :models, "
                " :active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "user_id": row.user_id,
                "name": row.label or model,
                "base_url": row.base_url or "",
                "key": row.api_key_encrypted or "",
                "fmt": row.api_format or "openai",
                "models": json.dumps([model] if model else [], ensure_ascii=False),
                "active": model,
            },
        )

    # 老库里用户选中的"平台免费模型"没有对应物，统一落回自己的配置
    if _has_table(inspector, "users"):
        user_cols = _columns(inspector, "users")
        if "ai_preference" in user_cols and "ai_active_config_id" in user_cols:
            conn.execute(
                text(
                    "UPDATE users SET ai_active_config_id = ("
                    "  SELECT c.id FROM ai_provider_configs c "
                    "  WHERE c.user_id = users.id ORDER BY c.id LIMIT 1"
                    ") WHERE ai_active_config_id IS NULL"
                )
            )
    return len(rows)


_AI_SHARES_DDL = """
CREATE TABLE ai_shares_new (
    id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    title VARCHAR(64) NOT NULL,
    base_url VARCHAR(255) NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    api_format VARCHAR(32) NOT NULL,
    models TEXT NOT NULL,
    active_model VARCHAR(128) NOT NULL,
    note VARCHAR(200) NOT NULL,
    is_active BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
)
"""


def _rebuild_shares(conn, inspector) -> int:
    """ai_shares 去掉单个 model 列、补上模型列表。

    SQLite 不能直接删列（且 model 还是 NOT NULL，留着会让新插入报错），
    只能按官方 12 步重建：建新表 → 搬数据 → 换名。整个过程关掉外键检查，
    换完再打开；子表（采纳/关闭记录）引用的是表名，重建后依旧指向新表。
    """
    if not _has_table(inspector, "ai_shares"):
        return 0
    cols = _columns(inspector, "ai_shares")
    if "model" not in cols:
        return 0  # 已是新结构

    old_rows = conn.execute(
        text(
            "SELECT id, owner_id, title, base_url, api_key_encrypted, api_format, "
            "model, note, is_active, created_at, updated_at FROM ai_shares"
        )
    ).all()

    was_foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(text("BEGIN"))
    try:
        conn.execute(text(_AI_SHARES_DDL))
        for row in old_rows:
            legacy_model = row.model or ""
            raw_models = None
            if "models" in cols:
                raw_models = conn.execute(
                    text("SELECT models FROM ai_shares WHERE id = :id"), {"id": row.id}
                ).scalar()
            models = []
            try:
                models = [str(m) for m in json.loads(raw_models or "[]")]
            except (TypeError, ValueError):
                models = []
            if not models and legacy_model:
                models = [legacy_model]
            active = ""
            if "active_model" in cols:
                active = conn.execute(
                    text("SELECT active_model FROM ai_shares WHERE id = :id"),
                    {"id": row.id},
                ).scalar() or ""
            if active not in models:
                active = models[0] if models else ""

            conn.execute(
                text(
                    "INSERT INTO ai_shares_new "
                    "(id, owner_id, title, base_url, api_key_encrypted, api_format, "
                    " models, active_model, note, is_active, created_at, updated_at) "
                    "VALUES (:id, :owner_id, :title, :base_url, :key, :fmt, "
                    " :models, :active, :note, :is_active, :created_at, :updated_at)"
                ),
                {
                    "id": row.id,
                    "owner_id": row.owner_id,
                    "title": row.title or active,
                    "base_url": row.base_url or "",
                    "key": row.api_key_encrypted or "",
                    "fmt": row.api_format or "openai",
                    "models": json.dumps(models, ensure_ascii=False),
                    "active": active,
                    "note": row.note or "",
                    "is_active": row.is_active,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                },
            )

        conn.execute(text("DROP TABLE ai_shares"))
        conn.execute(text("ALTER TABLE ai_shares_new RENAME TO ai_shares"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_ai_shares_owner_id "
                "ON ai_shares (owner_id)"
            )
        )
    finally:
        conn.execute(text(f"PRAGMA foreign_keys={was_foreign_keys}"))

    return len(old_rows)


def migrate_legacy_ai_config(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        # 生产环境走正式迁移，这里只管开发库
        return

    inspector = inspect(engine)
    if not _has_table(inspector, "ai_credentials") and not _has_table(
        inspector, "ai_shares"
    ):
        return

    with engine.begin() as conn:
        moved = _migrate_credentials(conn, inspector)
        if moved:
            logger.info("老 AI 凭据已迁移：%d 条", moved)
        shares = _rebuild_shares(conn, inspector)
        if shares:
            logger.info("老 AI 分享已重建：%d 条", shares)
