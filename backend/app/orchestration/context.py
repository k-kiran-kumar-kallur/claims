"""AgentContext injected into every node (spec §6.4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.core.logging import get_logger
from app.core.security import decrypt_str
from app.llm.gateway import CallContext, LLMGateway, get_gateway
from app.models import Claim, Claimant
from app.services import audit
from app.services.events import emit
from app.tools.registry import ToolRunner


@dataclass
class AgentContext:
    db: Session
    run_id: str
    claim_id: str
    node: str
    stage: str
    step_id: str
    correlation_id: str
    telemetry: list[dict] = field(default_factory=list)
    settings: Settings = field(default_factory=lambda: settings)
    _llm: LLMGateway | None = None
    _claimant_names: list[str] | None = None

    def __post_init__(self):
        from app.services.settings_service import effective_settings

        self.settings = effective_settings(self.db)
        self.log = get_logger(f"agent.{self.node}")
        self.tools = ToolRunner(self.node, self.step_id, self.run_id, self.telemetry)

    @property
    def llm(self) -> LLMGateway:
        if self._llm is None:
            self._llm = get_gateway()
        return self._llm

    @property
    def call_ctx(self) -> CallContext:
        if self._claimant_names is None:
            names: list[str] = []
            claim = self.db.get(Claim, self.claim_id)
            if claim:
                cl = self.db.get(Claimant, claim.claimant_id)
                name = decrypt_str(cl.full_name_enc) if cl else None
                if name:
                    names.append(name)
            self._claimant_names = names
        return CallContext(run_id=self.run_id, step_id=self.step_id, claimant_names=self._claimant_names)

    @property
    def claim(self) -> Claim:
        claim = self.db.get(Claim, self.claim_id)
        assert claim is not None
        return claim

    def commit(self) -> None:
        self.db.commit()

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Commit pending work first so the event never holds the SQLite write lock across sessions."""
        self.db.commit()
        emit(self.run_id, event_type, {"node": self.node, **(data or {})}, claim_id=self.claim_id)

    def audit(self, action: str, entity_type: str, entity_id: str | None = None, after: Any = None,
              before: Any = None) -> None:
        audit.record(self.db, action=action, entity_type=entity_type, entity_id=entity_id, claim_id=self.claim_id,
                     actor_type="agent", actor_id=self.node, before=before, after=after)
