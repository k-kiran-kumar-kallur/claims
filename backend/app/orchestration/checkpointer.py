"""LangGraph SQLite checkpointer in a separate file (ADR-005)."""
from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from app.config import settings

_saver: SqliteSaver | None = None


def get_checkpointer() -> SqliteSaver:
    global _saver
    if _saver is None:
        settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(settings.checkpoint_path), check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _saver = SqliteSaver(conn)
        _saver.setup()
    return _saver


def reset_checkpointer() -> None:
    global _saver
    if _saver is not None:
        _saver.conn.close()
    _saver = None
