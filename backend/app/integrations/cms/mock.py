"""MockCMSConnector: writes to the `cms_sync_log` outbox and returns a synthetic external reference."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.ids import uuid7
from app.core.security import sha256_hex
from app.integrations.cms.base import CMSConnector
from app.models import CmsSyncLog

_POLICIES = {
    "WC-2024-PA-087341": {"policy_number": "WC-PMA-55120983", "insurer": "PMA Companies", "tpa": "Lodestar Claims Management",
                          "coverage": "Pennsylvania statutory workers' compensation; employer's liability $500k/$500k/$500k",
                          "effective_from": "2024-01-01", "effective_to": "2024-12-31", "insured": "Keystone Industrial Services",
                          "status": "in_force", "source": "MockCMSConnector"},
}


class MockCMSConnector(CMSConnector):
    def lookup_policy(self, claim_number: str) -> dict:
        return _POLICIES.get(claim_number, {"status": "not_found", "source": "MockCMSConnector"})

    def post(self, db: Session, claim_id: str, payload: dict) -> dict:
        body = json.dumps(payload, sort_keys=True, default=str)
        entry = CmsSyncLog(id=uuid7(), claim_id=claim_id, entity_type=payload.get("entity_type", "decision_record"),
                           entity_id=payload.get("entity_id"), direction="outbound", payload=payload,
                           payload_hash=sha256_hex(body), status="sent", attempts=1,
                           external_ref=f"CMS-NOTE-{sha256_hex(body)[:10].upper()}")
        db.add(entry)
        return {"status": "sent", "external_ref": entry.external_ref, "sync_id": entry.id}
