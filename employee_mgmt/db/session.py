"""SQLAlchemy engine and session management for the Employee Management module.

Supports both local SQLite development and PostgreSQL/pgvector deployments
configured via `core/config.py`.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
import logging
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import settings
from .base import Base

logger = logging.getLogger("employee_mgmt.db")


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """Enforce foreign key constraints on every SQLite connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def build_engine(
    database_url: str | None = None,
    *,
    echo: bool | None = None,
) -> Engine:
    """Create a configured SQLAlchemy Engine for SQLite or PostgreSQL."""
    url = (database_url or settings.DATABASE_URL).strip()
    echo_sql = settings.DB_ECHO if echo is None else echo
    is_sqlite = url.lower().startswith("sqlite")

    engine_kwargs: dict[str, Any] = {
        "echo": echo_sql,
        "pool_pre_ping": True,
    }

    if is_sqlite:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10

    db_engine = create_engine(url, **engine_kwargs)

    if is_sqlite:
        event.listen(db_engine, "connect", _enable_sqlite_foreign_keys)

    return db_engine


engine: Engine = build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session per request.

    Rolls back automatically on unhandled exceptions and always closes the
    session when the request completes.
    """
    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def db_session_scope() -> Generator[Session, None, None]:
    """Transactional session scope for scripts, services, and background workers."""
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db_connection(target_engine: Engine | None = None) -> bool:
    """Verify database connectivity with a lightweight SELECT 1 probe."""
    active_engine = target_engine or engine
    try:
        with active_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        logger.warning("Database connectivity check failed.")
        return False


def init_db(target_engine: Engine | None = None) -> None:
    """Create all tables registered on `Base.metadata` (for dev/test bootstrap)."""
    active_engine = target_engine or engine
    Base.metadata.create_all(bind=active_engine)


def dispose_engine(target_engine: Engine | None = None) -> None:
    """Dispose pooled database connections cleanly during application shutdown."""
    active_engine = target_engine or engine
    active_engine.dispose()


__all__ = [
    "engine",
    "SessionLocal",
    "build_engine",
    "get_db",
    "db_session_scope",
    "check_db_connection",
    "init_db",
    "dispose_engine",
]