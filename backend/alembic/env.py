"""Alembic environment (render_as_batch for SQLite ALTER limitations, spec §11.4)."""
from alembic import context

import app.models  # noqa: F401 - register models
from app.db.base import Base
from app.db.session import get_engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
