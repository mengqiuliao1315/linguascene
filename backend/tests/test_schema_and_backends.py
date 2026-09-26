"""schema 补列、Alembic 升级，以及 Redis/S3 回落路径。"""

import os
import tempfile
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core import cache as cache_mod
from app.core import storage as storage_mod
from app.core.cache import InMemoryCache, get_cache, reset_cache
from app.core.config import settings
from app.core.schema_sync import apply_schema, sync_missing_columns
from app.core.storage import LocalStorage, get_storage, reset_storage


def test_sync_missing_columns_adds_token_version():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, "
                "username VARCHAR(64), "
                "email VARCHAR(255), "
                "password_hash VARCHAR(255)"
                ")"
            )
        )
    from app.core.database import Base
    import app.models  # noqa: F401

    applied = sync_missing_columns(engine, Base.metadata)
    assert any("token_version" in item for item in applied)
    columns = {col["name"] for col in inspect(engine).get_columns("users")}
    assert "token_version" in columns


def test_apply_schema_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    apply_schema(engine)
    apply_schema(engine)
    assert "users" in inspect(engine).get_table_names()
    columns = {col["name"] for col in inspect(engine).get_columns("users")}
    assert "token_version" in columns


def test_alembic_upgrade_creates_users_and_token_version(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = "sqlite:///" + Path(path).as_posix()
    monkeypatch.setattr(settings, "database_url", url)
    try:
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        cfg.set_main_option(
            "script_location",
            str(Path(__file__).resolve().parents[1] / "alembic"),
        )
        from alembic import command

        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert "users" in tables
            assert "alembic_version" in tables
            columns = {col["name"] for col in inspect(engine).get_columns("users")}
            assert "token_version" in columns
            with engine.connect() as conn:
                version = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            assert version == "0001_baseline"
        finally:
            engine.dispose()
    finally:
        Path(path).unlink(missing_ok=True)


def test_redis_backend_falls_back_when_unavailable(monkeypatch):
    reset_cache()
    monkeypatch.setattr(cache_mod.settings, "cache_backend", "redis")

    def boom(_url: str):
        raise ImportError("No module named redis")

    monkeypatch.setattr(cache_mod, "RedisCache", boom)
    try:
        assert isinstance(get_cache(), InMemoryCache)
    finally:
        reset_cache()


def test_s3_backend_falls_back_without_bucket(monkeypatch):
    reset_storage()
    monkeypatch.setattr(storage_mod.settings, "storage_backend", "s3")
    monkeypatch.setattr(storage_mod.settings, "s3_bucket", "")
    try:
        assert isinstance(get_storage(), LocalStorage)
    finally:
        reset_storage()


def test_s3_backend_falls_back_when_boto_missing(monkeypatch):
    reset_storage()
    monkeypatch.setattr(storage_mod.settings, "storage_backend", "s3")
    monkeypatch.setattr(storage_mod.settings, "s3_bucket", "demo")

    def boom():
        raise ImportError("No module named boto3")

    monkeypatch.setattr(storage_mod, "S3Storage", boom)
    try:
        assert isinstance(get_storage(), LocalStorage)
    finally:
        reset_storage()
