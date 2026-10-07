"""Сессии SQLAlchemy для SQLite-файла проекта."""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from paper2data.db.models import AppMeta, Base

_lock = threading.RLock()
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_db_path: Path | None = None


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _configure_sqlite(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_engine() -> Engine | None:
    with _lock:
        return _engine


def get_db_path() -> Path | None:
    with _lock:
        return _db_path


def init_project_db(db_path: Path) -> Engine:
    """Создаёт/открывает SQLite проекта и применяет базовую схему."""
    global _engine, _SessionLocal, _db_path

    db_path = Path(db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with _lock:
        if _engine is not None:
            _engine.dispose()

        engine = create_engine(
            _sqlite_url(db_path),
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )
        event.listen(engine, "connect", _configure_sqlite)
        try:
            from paper2data.db.migrate import ensure_migrations

            ensure_migrations(engine, db_path)
        except Exception:
            Base.metadata.create_all(engine)

        with Session(engine) as session:
            existing = session.get(AppMeta, "schema_version")
            if existing is None:
                session.add(AppMeta(key="schema_version", value="1"))
                session.commit()
            else:
                existing.value = "1"
                session.commit()

        _engine = engine
        _SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        _db_path = db_path
        return engine


def dispose_db() -> None:
    global _engine, _SessionLocal, _db_path
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _SessionLocal = None
        _db_path = None


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        raise RuntimeError("База проекта не инициализирована")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_db_alive() -> bool:
    engine = get_engine()
    if engine is None:
        return False
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


def get_meta(key: str) -> str | None:
    with session_scope() as session:
        row = session.get(AppMeta, key)
        return None if row is None else row.value


def set_meta(key: str, value: str) -> None:
    with session_scope() as session:
        row = session.get(AppMeta, key)
        if row is None:
            session.add(AppMeta(key=key, value=value))
        else:
            row.value = value
