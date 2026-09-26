from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------- 轻量迁移
# create_all 只会新建缺失的表，不会给已存在的表补列。新增的可选列在这里补上，
# 老库无需手工改表；复杂变更仍应使用正式的迁移工具。
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("ai_credentials", "api_format", "VARCHAR(32) DEFAULT 'openai'"),
    ("platform_ai_config", "api_format", "VARCHAR(32) DEFAULT 'openai'"),
    ("reading_notes", "lemma", "VARCHAR(128) DEFAULT ''"),
    ("reading_notes", "start_offset", "INTEGER DEFAULT 0"),
    ("reading_notes", "end_offset", "INTEGER DEFAULT 0"),
)


def ensure_columns() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table, column, ddl in _COLUMN_MIGRATIONS:
        if table not in tables:
            continue
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
