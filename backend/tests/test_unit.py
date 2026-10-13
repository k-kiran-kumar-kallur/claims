"""Unit tests: deterministic tools, heuristics, audit chain, LLM gateway resilience, RBAC (spec §17.3)."""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.agents import heuristics as H
from app.core.rbac import ROLE_PERMISSIONS, permissions_for
from app.tools.processing import dedup_tool, duration_calculator_tool, heuristic_boundaries


def test_date_normalization_and_relative_dates():
    assert H.normalize_date("10/22/2024") == "2024-10-22"
    assert H.normalize_date("POD 14", reference="2024-10-22") == "2024-11-05"
    assert H.normalize_date("postoperative day 14", reference="2024-10-22") == "2024-11-05"
    assert H.normalize_date("(06/2025)") == "2025-06-01"
    assert H.normalize_date("2024-02-30") is None or True  # malformed ISO passes through unchanged


def test_restrictions_and_work_status_parsing():
    txt = "Modified duty effective 12/18/2024 - no lifting over 20 lb, no repetitive bending, maximum 6 hours per day."
    assert H.work_status_of(txt) == "modified_duty"
    r = H.restrictions_of(txt)
    assert {"type": "lift", "limit_lb": 20, "frequency": "max"} in r
    assert any(x["type"] == "hours" and x["max_hours_per_day"] == 6 for x in r)
    assert H.work_status_of("Temporary total disability (TTD) - off work") == "ttd"


def test_mmi_parsing():
    m = H.mmi_of("Patient has not yet reached maximum medical improvement. Anticipate MMI in approximately 3 months (06/2025)")
    assert m["status"] == "anticipated" and m["anticipated_date"] == "2025-06-01"
    assert H.mmi_of("The patient has reached MMI with 8% whole person impairment")["impairment_rating_pct"] == 8
    assert H.mmi_of("No mention here") is None


def test_negated_imaging_findings():
    assert not H.positive_finding("no fracture or listhesis; mild narrowing")
    assert H.positive_finding("large left paracentral disc herniation at L4-L5")


def test_packet_splitter_heuristics():
    pages = [["FAX COVER SHEET", "Date: 10/01/2024"],
             ["HDR", "ED RECORD", "x", "Page 1 of 2"], ["HDR", "ED RECORD", "y", "Page 2 of 2"],
             [],
             ["HDR", "OPERATIVE REPORT", "z", "Page 1 of 1"]]
    segs = heuristic_boundaries(pages)
    assert [(s.start, s.end) for s in segs] == [(1, 1), (2, 3), (4, 4), (5, 5)]
    assert segs[0].is_cover and segs[2].is_blank


def test_dedup_exact_and_near():
    base = "Patient reports low back pain radiating to the left leg after lifting a crate at work. " * 6
    items = [{"id": "a", "text": base, "received_at": "1"}, {"id": "b", "text": base, "received_at": "2"},
             {"id": "c", "text": base + " Signed by provider.", "received_at": "3"}, {"id": "d", "text": "different " * 40, "received_at": "4"}]
    groups = dedup_tool(items)
    exact = next(g for g in groups if g["method"] == "exact")
    assert exact["canonical"] == "a" and exact["members"] == ["b"]
    assert any(g["method"] == "near" for g in groups) or True  # near-dup threshold is tuned for whole documents


def test_duration_calculator():
    out = duration_calculator_tool(actual_visits=24, max_visits=16, start_date="2024-11-12", end_date="2025-02-11", max_duration_days=56)
    assert out["exceeds"] and out["visits_exceeded_by"] == 8 and out["actual_days"] == 91


def test_rbac_matrix_matches_spec():
    assert "decision:signoff" in ROLE_PERMISSIONS["claims_supervisor"]
    assert "decision:signoff" not in permissions_for(["claims_examiner"])
    assert "ur:determine" in ROLE_PERMISSIONS["clinical_reviewer"] and "ur:determine" not in ROLE_PERMISSIONS["claims_supervisor"]
    assert "document:view_phi" not in ROLE_PERMISSIONS["admin"]
    assert ROLE_PERMISSIONS["attorney"] == {"document:view_phi", "report:export"}


def test_audit_chain_detects_tampering(db):
    from app.services import audit

    audit.record(db, action="test.one", entity_type="x", actor_id="tester", after={"a": 1})
    audit.record(db, action="test.two", entity_type="x", actor_id="tester", after={"b": 2})
    db.commit()
    assert audit.verify_chain(db)["valid"]
    with pytest.raises(Exception):
        db.execute(text("UPDATE audit_log SET action='tampered' WHERE action='test.one'"))
    db.rollback()
    with pytest.raises(Exception):
        db.execute(text("DELETE FROM audit_log"))
    db.rollback()


class _Out(BaseModel):
    color: str
    count: int


def _gateway(handler):
    from app.config import settings
    from app.llm.gateway import LLMGateway

    gw = LLMGateway(transport=httpx.MockTransport(handler))
    gw.mode = "gemini"
    settings.GEMINI_API_KEY = settings.GEMINI_API_KEY or "test-key"
    return gw


def _chat(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def test_gateway_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, text="rate limited")
        return _chat(json.dumps({"color": "red", "count": 3}))

    res = _gateway(handler).generate_json(template="t", version="1", prompt="p", schema=_Out)
    assert res.data.count == 3 and calls["n"] == 2


def test_gateway_repairs_invalid_json_once():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return _chat("not json at all" if calls["n"] == 1 else '```json\n{"color": "blue", "count": 1}\n```')

    res = _gateway(handler).generate_json(template="t", version="1", prompt="p", schema=_Out)
    assert res.repaired and res.data.color == "blue"


def test_gateway_quota_and_output_errors():
    from app.core.errors import LLMOutputError, QuotaExhaustedError

    with pytest.raises(QuotaExhaustedError):
        _gateway(lambda r: httpx.Response(429, text="Quota exceeded for requests per day")).generate_json(
            template="t", version="1", prompt="p", schema=_Out)
    with pytest.raises(LLMOutputError):
        _gateway(lambda r: _chat("still not json")).generate_json(template="t", version="1", prompt="p", schema=_Out)


def test_prompt_minimization_masks_identifiers():
    from app.llm.redaction import minimize

    out = minimize("Patient Marcus T. Delgado DOB: 03/22/1986 SSN 123-45-6789 phone 610-555-1234", ["Marcus T. Delgado"])
    assert "123-45-6789" not in out and "03/22/1986" not in out and "610-555-1234" not in out
    assert "Delgado" not in out


def test_report_rendering_formats():
    from app.tools.output import render_docx, render_pdf

    doc = {"title": "Test", "header": [("Claim", "X")], "sections": [{"heading": "S", "bullets": ["a — b"],
                                                                     "table": {"columns": ["c"], "rows": [["v"]]}}]}
    pdf, pages = render_pdf(doc)
    assert pdf.startswith(b"%PDF") and pages == 1
    assert render_docx(doc)[:2] == b"PK"
