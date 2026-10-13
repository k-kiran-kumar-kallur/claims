"""Runtime overrides of thresholds and model tiers managed by admins (app_settings), cached briefly."""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.db.session import SessionLocal
from app.models import AppSetting

_cache: dict[str, tuple[float, dict]] = {}


def _get(key: str, db: Session | None = None, ttl: float = 30.0) -> dict:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    own = db is None
    db = db or SessionLocal()
    try:
        row = db.get(AppSetting, key)
        value = dict(row.value or {}) if row and isinstance(row.value, dict) else {}
    except Exception:
        value = {}
    finally:
        if own:
            db.close()
    _cache[key] = (time.monotonic(), value)
    return value


def effective_settings(db: Session | None = None) -> Settings:
    overrides = {k: v for k, v in _get("thresholds", db).items() if hasattr(settings, k)}
    for k in ("TREATMENT_GAP_DAYS", "ONE_PAGE_WORD_LIMIT"):
        if k in overrides:
            overrides[k] = int(overrides[k])
    return settings.model_copy(update=overrides) if overrides else settings


def model_overrides() -> dict:
    return _get("models")


def clear_cache() -> None:
    _cache.clear()
