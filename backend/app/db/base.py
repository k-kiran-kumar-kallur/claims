from __future__ import annotations

from sqlalchemy import JSON, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import now_iso, uuid7

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict: JSON, list: JSON}

    def to_dict(self, exclude: set[str] | None = None) -> dict:
        exclude = exclude or set()
        return {c.name: getattr(self, c.key) for c in self.__table__.columns if c.name not in exclude}


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[str] = mapped_column(String(30), default=now_iso, nullable=False)


class MutableMixin(TimestampMixin):
    updated_at: Mapped[str] = mapped_column(String(30), default=now_iso, onupdate=now_iso, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
