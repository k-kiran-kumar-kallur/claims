"""Auth and users (spec §12.1, §15.2)."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, envelope, get_db, require_permission
from app.config import settings
from app.core import totp
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound, Unauthorized
from app.core.ids import now_iso, parse_iso, to_iso, utcnow, uuid7
from app.core.rbac import ROLES, permissions_for
from app.core.security import (
    create_access_token,
    decrypt_str,
    encrypt_str,
    hash_password,
    new_refresh_token,
    sha256_hex,
    validate_password_strength,
    verify_password,
)
from app.main_limiter import limiter
from app.models import RefreshToken, Role, User, UserRole
from app.services import audit
from app.services.actions import Principal

router = APIRouter(tags=["auth"])
COOKIE = "claims_refresh"
COOKIE_PATH = "/api/v1/auth"


class LoginIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    password: str = Field(min_length=1, max_length=256)
    mfa_code: str | None = None


def _issue(db: Session, response: Response, user: User, request: Request) -> dict:
    token, ttl = create_access_token(user.id, user.role_keys)
    raw, digest = new_refresh_token()
    db.add(RefreshToken(id=uuid7(), user_id=user.id, token_hash=digest,
                        expires_at=to_iso(utcnow() + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)),
                        user_agent=(request.headers.get("user-agent") or "")[:255], ip=request.client.host if request.client else None))
    response.set_cookie(COOKIE, raw, httponly=True, secure=settings.COOKIE_SECURE or settings.is_production, samesite="strict",
                        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400, path=COOKIE_PATH)
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl}


def _csrf(request: Request) -> None:
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise Forbidden("Missing CSRF header")


@router.post("/auth/login")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def login(request: Request, body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    ip = request.client.host if request.client else None
    if user and user.locked_until and parse_iso(user.locked_until) > utcnow():
        raise Unauthorized("Account temporarily locked after repeated failed attempts")
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.MAX_FAILED_LOGINS:
                user.locked_until = to_iso(utcnow() + timedelta(minutes=settings.LOCKOUT_MINUTES))
                user.failed_login_count = 0
        audit.record(db, action="auth.failed", entity_type="user", entity_id=user.id if user else None, actor_type="system",
                     actor_id="auth", after={"email": body.email}, ip=ip)
        db.commit()
        raise Unauthorized("Invalid email or password")
    if user.mfa_secret_enc:
        if not body.mfa_code:
            raise Unauthorized("MFA code required")
        if not totp.verify(decrypt_str(user.mfa_secret_enc) or "", body.mfa_code):
            raise Unauthorized("Invalid MFA code")
    elif settings.is_production and {"claims_supervisor", "admin"} & set(user.role_keys):
        raise Forbidden("MFA enrollment is required for this role")
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now_iso()
    audit.record(db, action="auth.login", entity_type="user", entity_id=user.id, actor_id=user.id, ip=ip,
                 user_agent=request.headers.get("user-agent"))
    return envelope(_issue(db, response, user, request))


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    _csrf(request)
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise Unauthorized("No refresh token")
    row = db.execute(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw))).scalar_one_or_none()
    if row is None or parse_iso(row.expires_at) < utcnow():
        raise Unauthorized("Refresh token invalid")
    if row.revoked_at:  # token reuse -> revoke the whole family (theft detection)
        for t in db.execute(select(RefreshToken).where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))).scalars():
            t.revoked_at = now_iso()
        db.commit()
        raise Unauthorized("Refresh token reuse detected")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("User inactive")
    row.revoked_at = now_iso()
    out = _issue(db, response, user, request)
    return envelope(out)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    _csrf(request)
    raw = request.cookies.get(COOKIE)
    if raw:
        row = db.execute(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw))).scalar_one_or_none()
        if row and not row.revoked_at:
            row.revoked_at = now_iso()
            audit.record(db, action="auth.logout", entity_type="user", entity_id=row.user_id, actor_id=row.user_id)
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.status_code = 204
    return response


def user_dict(u: User) -> dict:
    roles = u.role_keys
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "roles": roles, "is_active": u.is_active,
            "permissions": sorted(permissions_for(roles)), "team": u.team, "last_login_at": u.last_login_at,
            "mfa_enabled": bool(u.mfa_secret_enc)}


@router.get("/users/me")
def me(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    return envelope({**user_dict(db.get(User, user.id)), "idle_logout_minutes": settings.IDLE_LOGOUT_MINUTES,
                     "llm_mode": settings.llm_mode})


@router.get("/users")
def list_users(role: str | None = None, db: Session = Depends(get_db), _: Principal = Depends(current_user)):
    """Directory for assignment pickers (names and roles only)."""
    users = db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).scalars().all()
    out = [{"id": u.id, "full_name": u.full_name, "roles": u.role_keys} for u in users]
    return envelope([u for u in out if not role or role in u["roles"]])


@router.post("/users/me/mfa")
def enroll_mfa(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    secret = totp.new_secret()
    u.mfa_secret_enc = encrypt_str(secret)
    audit.record(db, action="auth.mfa_enroll", entity_type="user", entity_id=u.id, actor_id=u.id)
    return envelope({"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, u.email)})


# ---- admin: users and roles ----------------------------------------------------------------------

class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    full_name: str = Field(min_length=2, max_length=200)
    password: str
    roles: list[str] = Field(min_length=1)
    team: str = "default"


class UserPatch(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None
    password: str | None = None
    team: str | None = None


def _set_roles(db: Session, u: User, roles: list[str], granted_by: str) -> None:
    bad = [r for r in roles if r not in ROLES]
    if bad:
        raise BadRequest(f"Unknown roles {bad}")
    role_rows = {r.key: r for r in db.execute(select(Role)).scalars()}
    for ur in db.execute(select(UserRole).where(UserRole.user_id == u.id)).scalars():
        db.delete(ur)
    db.flush()
    for r in roles:
        db.add(UserRole(user_id=u.id, role_id=role_rows[r].id, granted_by=granted_by))


@router.get("/admin/users")
def admin_users(db: Session = Depends(get_db), _: Principal = Depends(require_permission("config:manage"))):
    return envelope([user_dict(u) for u in db.execute(select(User).order_by(User.email)).scalars()])


@router.post("/admin/users", status_code=201)
def admin_create_user(body: UserIn, db: Session = Depends(get_db), admin: Principal = Depends(require_permission("config:manage"))):
    if db.execute(select(User.id).where(User.email == body.email.lower())).first():
        raise Conflict("Email already registered")
    validate_password_strength(body.password)
    u = User(id=uuid7(), email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password), team=body.team)
    db.add(u)
    db.flush()
    _set_roles(db, u, body.roles, admin.id)
    audit.record(db, action="role.grant", entity_type="user", entity_id=u.id, actor_id=admin.id, after={"roles": body.roles})
    db.flush()
    db.refresh(u)
    return envelope(user_dict(u))


@router.patch("/admin/users/{user_id}")
def admin_update_user(user_id: str, body: UserPatch, db: Session = Depends(get_db),
                      admin: Principal = Depends(require_permission("config:manage"))):
    u = db.get(User, user_id)
    if u is None:
        raise NotFound("User not found")
    before = user_dict(u)
    if body.full_name:
        u.full_name = body.full_name
    if body.is_active is not None:
        if u.id == admin.id and not body.is_active:
            raise BadRequest("You cannot deactivate yourself")
        u.is_active = body.is_active
    if body.team:
        u.team = body.team
    if body.password:
        validate_password_strength(body.password)
        u.password_hash = hash_password(body.password)
    if body.roles is not None:
        _set_roles(db, u, body.roles, admin.id)
    db.flush()
    db.refresh(u)
    audit.record(db, action="role.grant" if body.roles is not None else "user.update", entity_type="user", entity_id=u.id,
                 actor_id=admin.id, before={"roles": before["roles"], "is_active": before["is_active"]},
                 after={"roles": u.role_keys, "is_active": u.is_active})
    return envelope(user_dict(u))
