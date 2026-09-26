"""把当前模型补到已有库：建缺失的表，给已有表加缺失的列。

`create_all` 不会改已存在的表。开发启动、seed 和 Alembic 升级都走这里，
避免 SQLite 和 Postgres 各写一份加法变更。
"""

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
    """给已存在但缺列的表补上 ALTER TABLE，返回实际执行的语句。"""
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


def sync_sqlite_columns(engine: Bind, metadata: MetaData) -> list[str]:
    """兼容旧入口。"""
    return sync_missing_columns(engine, metadata)


def apply_schema(bind: Bind) -> None:
    """建齐当前模型对应的表，并给旧表补上缺失列。"""
    from app.core.database import Base
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=bind)
    sync_missing_columns(bind, Base.metadata)
