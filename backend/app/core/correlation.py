"""Correlation-id propagation (HTTP request -> run -> step -> tool/LLM call -> audit)."""
from __future__ import annotations

import contextvars
import uuid

correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
claim_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("claim_id", default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
node_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("node", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str:
    cid = correlation_id_var.get()
    if not cid:
        cid = new_correlation_id()
        correlation_id_var.set(cid)
    return cid
