"""Run events (the SSE source, spec §12.4) and notifications."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.models import Notification, RunEvent


def emit(run_id: str, event_type: str, data: dict[str, Any] | None = None, claim_id: str | None = None,
         db: Session | None = None) -> None:
    """Append a run event.  Uses its own short transaction unless a session is passed."""
    ev = RunEvent(run_id=run_id, claim_id=claim_id, event_type=event_type, data=data or {})
    if db is not None:
        db.add(ev)
        return
    with session_scope() as s:
        s.add(ev)


def events_after(db: Session, run_id: str, last_id: int, limit: int = 200) -> list[RunEvent]:
    return list(db.execute(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                           .order_by(RunEvent.id).limit(limit)).scalars())


def notify(db: Session, user_id: str, kind: str, title: str, body: str | None = None, claim_id: str | None = None,
           link: str | None = None) -> None:
    db.add(Notification(user_id=user_id, kind=kind, title=title, body=body, claim_id=claim_id, link=link))
