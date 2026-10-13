"""Append-only, hash-chained audit log (spec §16.4).

Chain rule: hash = SHA-256(prev_hash || canonical_json(row)).  The row is first inserted with a placeholder
hash, which takes SQLite's write lock, so reading the previous hash and sealing the row is serialized across
the API and worker processes.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.correlation import get_correlation_id
from app.core.security import sha256_hex
from app.models import AuditLog

PENDING = "__pending__"
GENESIS = "0" * 64


def _canonical(row: AuditLog) -> str:
    body = {
        "id": row.id, "ts": row.ts, "actor_type": row.actor_type, "actor_id": row.actor_id, "action": row.action,
        "entity_type": row.entity_type, "entity_id": row.entity_id, "claim_id": row.claim_id,
        "before": row.before, "after": row.after, "correlation_id": row.correlation_id,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, row: AuditLog) -> str:
    return sha256_hex((prev_hash or GENESIS) + _canonical(row))


def record(db: Session, *, action: str, entity_type: str, entity_id: str | None = None, claim_id: str | None = None,
           actor_type: str = "user", actor_id: str = "system", before: Any = None, after: Any = None,
           ip: str | None = None, user_agent: str | None = None) -> AuditLog:
    row = AuditLog(actor_type=actor_type, actor_id=actor_id or "system", action=action, entity_type=entity_type,
                   entity_id=entity_id, claim_id=claim_id, before=_jsonable(before), after=_jsonable(after), ip=ip,
                   user_agent=(user_agent or "")[:255] or None, correlation_id=get_correlation_id(), hash=PENDING)
    db.add(row)
    db.flush()  # INSERT -> holds the SQLite write lock until commit
    prev = db.execute(select(AuditLog.hash).where(AuditLog.id < row.id).order_by(AuditLog.id.desc()).limit(1)).scalar()
    prev_hash = prev or GENESIS
    set_committed_value(row, "prev_hash", prev_hash)
    digest = compute_hash(prev_hash, row)
    db.execute(text("UPDATE audit_log SET prev_hash=:p, hash=:h WHERE id=:id"), {"p": prev_hash, "h": digest, "id": row.id})
    set_committed_value(row, "hash", digest)  # never re-flushed by the ORM (the table is append-only)
    return row


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    count = 0
    for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        count += 1
        if row.prev_hash != prev:
            return {"valid": False, "checked": count, "broken_at_id": row.id, "reason": "prev_hash mismatch"}
        if compute_hash(row.prev_hash, row) != row.hash:
            return {"valid": False, "checked": count, "broken_at_id": row.id, "reason": "hash mismatch"}
        prev = row.hash
    return {"valid": True, "checked": count, "head_hash": prev}


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))
