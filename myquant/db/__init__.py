"""SQLAlchemy 引擎与 Session 工厂。SQLite WAL 模式，单文件。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import DB_FILE

_DB_URL = f"sqlite:///{DB_FILE.as_posix()}"

engine: Engine = create_engine(
    _DB_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - infra
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务作用域。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
