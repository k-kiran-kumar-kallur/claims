"""Test configuration: isolated data dir, deterministic rules mode (no network), no in-process worker."""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="claims-ai-test-")
os.environ.update({
    "APP_ENV": "test", "DATA_DIR": _TMP, "SECRETS_DIR": os.path.join(_TMP, "secrets"), "LLM_PROVIDER": "rules",
    "RUN_WORKER_IN_PROCESS": "false", "SEED_DEMO_DATA": "false", "LOG_LEVEL": "WARNING", "RATE_LIMIT_DEFAULT": "10000/minute",
    "RATE_LIMIT_LOGIN": "1000/minute",
})

import warnings

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)


@pytest.fixture(scope="session", autouse=True)
def _db():
    from app.core.logging import configure_logging
    from app.db.init_db import init_db
    from app.db.session import session_scope
    from app.seed.reference import seed_guidelines, seed_reference, seed_users

    configure_logging("WARNING", "test")
    init_db()
    with session_scope() as db:
        seed_reference(db)
        seed_users(db)
        seed_guidelines(db)
    yield


@pytest.fixture()
def db():
    from app.db.session import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def principal(db, email: str):
    from sqlalchemy import select

    from app.core.rbac import permissions_for
    from app.models import User
    from app.services.actions import Principal

    u = db.execute(select(User).where(User.email == email)).scalar_one()
    return Principal(id=u.id, email=u.email, full_name=u.full_name, roles=u.role_keys, permissions=permissions_for(u.role_keys))
