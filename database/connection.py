"""Minimal SQLAlchemy infrastructure for the Dragon World PostgreSQL runtime.

This module owns configuration and connection/session construction only. It
does not define ORM models, create tables, or migrate the existing JSON stores.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


class DatabaseConfigurationError(RuntimeError):
    """Raised when the PostgreSQL application connection is not configured."""


def get_database_url() -> str:
    """Load and return DATABASE_URL without exposing it in logs or errors."""

    load_dotenv(ENV_PATH)
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise DatabaseConfigurationError(
            "未配置 DATABASE_URL，请在项目根目录 .env 中填写 PostgreSQL 连接地址。"
        )
    return database_url


def create_database_engine() -> Engine:
    """Create a SQLAlchemy engine; the first operation opens the connection."""

    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the shared SQLAlchemy 2.x Session factory for future ORM work."""

    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    """Provide a managed Session without committing implicitly."""

    with session_factory() as session:
        yield session
