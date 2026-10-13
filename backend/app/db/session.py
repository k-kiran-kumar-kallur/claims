"""SQLAlchemy engine with the SQLite operational pragmas from spec §11.4."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _set_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "REPLAC")


def _defer_fks(conn, cursor, statement, parameters, context, executemany) -> None:
    """Open the write transaction just before the first write and defer FK checks to COMMIT.

    FK integrity is still enforced, but insert order inside a unit of work no longer matters.  Reads stay outside
    write transactions (pysqlite default), so long-running agent nodes never hold the SQLite write lock while
    waiting on the network."""
    dbapi = conn.connection.dbapi_connection
    if not dbapi.in_transaction and statement.lstrip()[:6].upper() in _WRITE_PREFIXES:
        dbapi.execute("BEGIN")
        dbapi.execute("PRAGMA defer_foreign_keys=ON")


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False, "timeout": 30},
                                pool_pre_ping=True)
        event.listen(_engine, "connect", _set_pragmas)
        event.listen(_engine, "before_cursor_execute", _defer_fks)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def SessionLocal() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_engine() -> None:
    """Testing helper: dispose of the engine so a new DATA_DIR is picked up."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None
