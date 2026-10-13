"""Initial schema: all ORM tables plus SQLite objects (FTS5, append-only audit triggers, JSON checks).

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-09
"""
from alembic import op
from sqlalchemy import text

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base
    from app.db.init_db import SQLITE_DDL

    bind = op.get_bind()
    Base.metadata.create_all(bind)
    for stmt in SQLITE_DDL:
        bind.execute(text(stmt))


def downgrade() -> None:
    raise RuntimeError("Downgrading the initial schema would destroy the audit trail; restore from backup instead.")
