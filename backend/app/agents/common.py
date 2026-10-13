"""Helpers shared by agents: LLM-with-fallback calls, flags, document requests."""
from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select

from app.agents.prompts.registry import get_prompt
from app.core.errors import LLMOutputError, LLMUnavailableError, SafetyBlockError
from app.core.ids import uuid7
from app.models import DocumentRequest, Flag
from app.orchestration.context import AgentContext

T = TypeVar("T", bound=BaseModel)


def run_llm(ctx: AgentContext, prompt_name: str, schema: type[T], images: list[bytes] | None = None,
            **variables: Any) -> tuple[T | None, str]:
    """Call Gemini with a versioned prompt.  Returns (result, source) where source is llm | rules | rules_fallback.

    Transient errors (429/5xx/timeouts) propagate so the node is retried from its checkpoint; output/safety errors
    and rules mode return None so the agent uses its deterministic implementation (graceful degradation §14.2).
    """
    if not ctx.llm.enabled:
        return None, "rules"
    ctx.db.commit()  # never hold the SQLite write lock while waiting on the network
    p = get_prompt(ctx.db, prompt_name)
    try:
        res = ctx.llm.generate_json(template=p.name, version=p.version, prompt=p.render(**variables), system=p.system,
                                    schema=schema, tier=p.tier, temperature=p.temperature, images=images,
                                    ctx=ctx.call_ctx)
        return res.data, "llm"
    except LLMUnavailableError:
        return None, "rules"
    except (LLMOutputError, SafetyBlockError) as exc:
        ctx.log.warning("llm_fallback_to_rules", prompt=prompt_name, error=str(exc)[:300])
        return None, "rules_fallback"


def upsert_flag(ctx: AgentContext, item_key: str, **fields: Any) -> Flag:
    """Idempotent flag creation keyed by (claim, item_key); human actions on an existing flag are preserved."""
    existing = ctx.db.execute(select(Flag).where(Flag.claim_id == ctx.claim_id, Flag.item_key == item_key)).scalar_one_or_none()
    if existing:
        if existing.human_action is None:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.run_id = ctx.run_id
        return existing
    flag = Flag(id=uuid7(), claim_id=ctx.claim_id, run_id=ctx.run_id, item_key=item_key, **fields)
    ctx.db.add(flag)
    return flag


def upsert_document_request(ctx: AgentContext, dedup_key: str, description: str, reason: str,
                            requested_from: str | None = None, due_date: str | None = None) -> DocumentRequest:
    existing = ctx.db.execute(select(DocumentRequest).where(DocumentRequest.claim_id == ctx.claim_id,
                                                            DocumentRequest.dedup_key == dedup_key)).scalar_one_or_none()
    if existing:
        return existing
    req = DocumentRequest(id=uuid7(), claim_id=ctx.claim_id, description=description, reason=reason,
                          requested_from=requested_from, due_date=due_date, source="agent", dedup_key=dedup_key)
    ctx.db.add(req)
    return req


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "undated"
    y, m, d = iso[:10].split("-")
    return f"{m}/{d}/{y}"
