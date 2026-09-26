from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.schema import Column, MetaData

logger = logging.getLogger(__name__)

Bind = Engine | Connection


def _column_ddl_type(bind: Bind, column: Column) -> str:
    try:
        return column.type.compile(dialect=bind.dialect)
    except Exception:  # noqa: BLE001 - 编译失败时退回 TEXT
        return "TEXT"


def _literal_default(column: Column) -> str | None:
    default = column.default
    if default is None or getattr(default, "is_callable", False):
        return None

    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def _execute_on_connection(bind: Bind, statements: list[str]) -> None:
    if not statements:
        return
    if isinstance(bind, Engine):
        with bind.begin() as connection:
            for ddl in statements:
                connection.execute(text(ddl))
        return
    for ddl in statements:
        bind.execute(text(ddl))


def sync_missing_columns(bind: Bind, metadata: MetaData) -> list[str]:
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []
    preparer = bind.dialect.identifier_preparer

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue

            ddl = (
                f"ALTER TABLE {preparer.quote(table.name)} "
                f"ADD COLUMN {preparer.quote(column.name)} "
                f"{_column_ddl_type(bind, column)}"
            )
            default = _literal_default(column)
            if default is not None:
                ddl += f" DEFAULT {default}"
            applied.append(ddl)

    _execute_on_connection(bind, applied)
    if applied:
        logger.info("schema 同步：补了 %d 个列", len(applied))
    return applied


def drop_orphan_columns(bind: Bind, metadata: MetaData) -> list[str]:
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    dropped: list[str] = []
    preparer = bind.dialect.identifier_preparer

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        model_columns = {column.name for column in table.columns}
        for column in inspector.get_columns(table.name):
            name = column["name"]
            if name in model_columns:
                continue

            # 模型里删掉的字段会以 NOT NULL 列留在老库里，插入新行时缺值会报
            # IntegrityError，所以启动时顺手清掉。
            ddl = (
                f"ALTER TABLE {preparer.quote(table.name)} "
                f"DROP COLUMN {preparer.quote(name)}"
            )
            try:
                _execute_on_connection(bind, [ddl])
            except Exception as exc:  # noqa: BLE001 - 删不掉就保留，不影响启动
                logger.warning(
                    "schema 同步：旧列 %s.%s 删除失败，已保留（%s）",
                    table.name,
                    name,
                    exc,
                )
                continue
            dropped.append(ddl)

    if dropped:
        logger.info("schema 同步：清理了 %d 个旧列", len(dropped))
    return dropped


def apply_schema(bind: Bind) -> None:
    from app.core.database import Base
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=bind)
    sync_missing_columns(bind, Base.metadata)
    drop_orphan_columns(bind, Base.metadata)
