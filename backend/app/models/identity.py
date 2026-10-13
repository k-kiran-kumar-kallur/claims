from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import now_iso
from app.db.base import Base, IdMixin, MutableMixin, TimestampMixin


class User(IdMixin, MutableMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    team: Mapped[str] = mapped_column(String(64), default="default")
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text)
    last_login_at: Mapped[str | None] = mapped_column(String(30))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[str | None] = mapped_column(String(30))

    roles: Mapped[list[Role]] = relationship(secondary="user_roles", primaryjoin="User.id == UserRole.user_id",
                                             secondaryjoin="Role.id == UserRole.role_id", lazy="selectin",
                                             viewonly=True)

    @property
    def role_keys(self) -> list[str]:
        return sorted(r.key for r in self.roles)


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"
    permission_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_key: Mapped[str] = mapped_column(ForeignKey("permissions.permission_key", ondelete="CASCADE"),
                                                primary_key=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    granted_by: Mapped[str | None] = mapped_column(String(36))
    granted_at: Mapped[str] = mapped_column(String(30), default=now_iso)


class RefreshToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[str] = mapped_column(String(30))
    revoked_at: Mapped[str | None] = mapped_column(String(30))
    replaced_by: Mapped[str | None] = mapped_column(String(36))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))
