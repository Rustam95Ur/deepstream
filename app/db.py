"""SQLAlchemy engines, sessions, Alembic. App traffic via PgBouncer; migrations hit Postgres."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_engine: Engine | None = None
_migrate_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return int(raw)


def database_url() -> str:
    return (
        os.environ.get("NEXUS_DS_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
    ).strip()


def migrate_database_url() -> str:
    return (os.environ.get("NEXUS_DS_DATABASE_MIGRATE_URL") or database_url()).strip()


def db_enabled() -> bool:
    return bool(database_url())


def _connect_args() -> dict:
    # prepare_threshold is a psycopg client flag (PgBouncer transaction mode).
    # Do not pass GUCs via libpq `options`: PgBouncer rejects statement_timeout there.
    return {"prepare_threshold": None}


def _attach_session_gucs(engine: Engine, *, statement_timeout_ms: int) -> None:
    timeout_ms = int(statement_timeout_ms)

    @event.listens_for(engine, "checkout")
    def _set_gucs(dbapi_conn, _connection_record, _connection_proxy) -> None:  # noqa: ANN001
        # Transaction pooling: SET must run on checkout, not only on connect.
        with dbapi_conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {timeout_ms}")
            cur.execute("SET idle_in_transaction_session_timeout = 10000")
            cur.execute("SET timezone = 'UTC'")


def _make_engine(
    url: str, *, pool_size: int, max_overflow: int, statement_timeout_ms: int
) -> Engine:
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=_env_int("NEXUS_DS_DB_POOL_RECYCLE", 180),
        pool_timeout=_env_int("NEXUS_DS_DB_POOL_TIMEOUT", 10),
        pool_use_lifo=True,
        connect_args=_connect_args(),
    )
    _attach_session_gucs(engine, statement_timeout_ms=statement_timeout_ms)
    return engine


def get_engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        url = database_url()
        if not url:
            raise RuntimeError("NEXUS_DS_DATABASE_URL is required")
        _engine = _make_engine(
            url,
            pool_size=_env_int("NEXUS_DS_DB_POOL_SIZE", 20),
            max_overflow=_env_int("NEXUS_DS_DB_MAX_OVERFLOW", 40),
            statement_timeout_ms=_env_int("NEXUS_DS_DB_STATEMENT_TIMEOUT_MS", 5000),
        )
        _Session = sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_migrate_engine() -> Engine:
    global _migrate_engine
    if _migrate_engine is None:
        url = migrate_database_url()
        if not url:
            raise RuntimeError("NEXUS_DS_DATABASE_MIGRATE_URL is required")
        _migrate_engine = _make_engine(
            url,
            pool_size=2,
            max_overflow=0,
            statement_timeout_ms=120000,
        )
    return _migrate_engine


def _alembic_config() -> Config:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", migrate_database_url())
    return cfg


def init_db() -> None:
    if not db_enabled():
        raise RuntimeError("NEXUS_DS_DATABASE_URL is required")
    engine = get_migrate_engine()
    cfg = _alembic_config()
    inspector = inspect(engine)
    if inspector.has_table("cameras") and not inspector.has_table("alembic_version"):
        command.stamp(cfg, "0001_initial")
        logger.info("Existing schema stamped as 0001_initial")
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations applied")
    get_engine()


@contextmanager
def session_scope(*, write: bool = False) -> Iterator[Session]:
    if _Session is None:
        get_engine()
    assert _Session is not None
    session = _Session()
    try:
        yield session
        if write:
            session.commit()
        else:
            # Rollback expires ORM instances even with expire_on_commit=False.
            # Copy attributes before leaving this block.
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
