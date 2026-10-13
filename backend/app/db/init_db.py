"""Schema creation: ORM tables + SQLite-specific objects (FTS5, append-only triggers, JSON checks)."""
from __future__ import annotations

from sqlalchemy import text

from app.db.base import Base
from app.db.session import get_engine

SQLITE_DDL = [
    # Full-text search (spec §5.5, §11.3)
    """CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(text, page_id UNINDEXED, claim_id UNINDEXED,
       document_id UNINDEXED, page_number UNINDEXED, tokenize='porter unicode61')""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS guideline_rules_fts USING fts5(text, rule_id UNINDEXED,
       tokenize='porter unicode61')""",
    # audit_log is append-only (spec §11.3, §16.4)
    # the only permitted update is filling in the hash of a freshly inserted row (see services/audit.py)
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
       WHEN OLD.hash <> '__pending__' BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
       BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""",
    # JSON validity guards on the most important JSON columns
    """CREATE TRIGGER IF NOT EXISTS extracted_facts_json_check BEFORE INSERT ON extracted_facts
       WHEN NOT json_valid(NEW.value) BEGIN SELECT RAISE(ABORT, 'extracted_facts.value must be JSON'); END""",
    # sealed decisions are immutable
    """CREATE TRIGGER IF NOT EXISTS decisions_sealed_immutable BEFORE UPDATE ON decisions
       WHEN OLD.status = 'sealed' BEGIN SELECT RAISE(ABORT, 'sealed decision records are immutable'); END""",
]


def init_db() -> None:
    import app.models  # noqa: F401 - register models

    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in SQLITE_DDL:
            conn.execute(text(stmt))
