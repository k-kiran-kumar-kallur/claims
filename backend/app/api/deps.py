"""FastAPI dependencies: authentication, RBAC (`require_permission`), claim scoping, pagination, envelopes."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import jwt
from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.correlation import user_id_var
from app.core.errors import Forbidden, Unauthorized
from app.core.rbac import permissions_for
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import Claim, User
from app.services.actions import Principal
from app.services.claims import get_claim_for


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token")
    try:
        payload = decode_access_token(auth.split(" ", 1)[1])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Invalid token") from exc
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise Unauthorized("User inactive")
    roles = user.role_keys
    user_id_var.set(user.id)
    return Principal(id=user.id, email=user.email, full_name=user.full_name, roles=roles, permissions=permissions_for(roles),
                     ip=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"),
                     team=user.team)


def require_permission(*perms: str):
    """Deny by default: the user needs at least one of the listed permissions."""
    def dep(user: Principal = Depends(current_user)) -> Principal:
        if not any(user.has(p) for p in perms):
            raise Forbidden(f"Requires permission: {' or '.join(perms)}")
        return user
    return dep


def require_role(*roles: str):
    def dep(user: Principal = Depends(current_user)) -> Principal:
        if not set(roles) & set(user.roles):
            raise Forbidden(f"Requires role: {' or '.join(roles)}")
        return user
    return dep


def claim_access(claim_id: str, db: Session = Depends(get_db), user: Principal = Depends(require_permission("document:view_phi"))) -> Claim:
    return get_claim_for(db, user, claim_id)


class Paging:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)):
        self.page, self.page_size = page, page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def envelope(data: Any, **meta: Any) -> dict:
    return {"data": data, "meta": meta}
