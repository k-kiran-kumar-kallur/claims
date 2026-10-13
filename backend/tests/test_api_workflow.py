"""API integration test: full end-to-end workflow on the synthetic sample claim, driven by each persona through
every HITL checkpoint (spec §17.3 E2E: upload -> HITL-1 -> validate facts -> approve summary -> decide -> sign off)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PW = "Demo!Passw0rd"


@pytest.fixture(scope="module")
def client():
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def login(client, email: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def drain():
    from app.worker import Worker
    Worker().drain()


def pending_review(client, h, claim_id, checkpoint):
    r = client.get("/api/v1/reviews", params={"claim_id": claim_id, "checkpoint": checkpoint}, headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    assert items, f"no pending {checkpoint}"
    return client.get(f"/api/v1/reviews/{items[0]['id']}", headers=h).json()["data"]


def test_health_and_auth(client):
    assert client.get("/api/v1/health/live").json()["status"] == "ok"
    assert client.post("/api/v1/auth/login", json={"email": "summ@claims.example", "password": "wrong"}).status_code == 401
    assert client.get("/api/v1/claims").status_code == 401
    h = login(client, "summ@claims.example")
    me = client.get("/api/v1/users/me", headers=h).json()["data"]
    assert me["roles"] == ["summarization_team"] and "claim:create" in me["permissions"]
    r = client.get("/api/v1/claims", headers=login(client, "admin@claims.example"))
    assert r.status_code == 403 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["correlation_id"]


def test_refresh_requires_csrf_header_and_rotates(client):
    client.cookies.clear()
    login(client, "ncm@claims.example")
    assert client.post("/api/v1/auth/refresh").status_code == 403
    r = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 200 and r.json()["data"]["access_token"]


def test_end_to_end_workflow(client):
    from app.seed.sample_package import CLAIM, build_files

    summ = login(client, "summ@claims.example")
    examiner, ncm = login(client, "examiner@claims.example"), login(client, "ncm@claims.example")
    reviewer, supervisor = login(client, "reviewer@claims.example"), login(client, "supervisor@claims.example")
    users = {u["full_name"]: u["id"] for u in client.get("/api/v1/users", headers=summ).json()["data"]}

    body = {**{k: v for k, v in CLAIM.items() if k != "adjuster_name"}, "claim_number": "WC-2024-PA-TEST01",
            "assigned_adjuster_id": users["Jennifer Hartwell"], "assigned_ncm_id": users["Nora Castillo, RN"],
            "assigned_reviewer_id": users["Dr. Lena Brooks"], "assigned_supervisor_id": users["Marcus Bell"]}
    assert client.post("/api/v1/claims", json=body, headers=login(client, "reviewer@claims.example")).status_code == 403
    r = client.post("/api/v1/claims", json=body, headers=summ)
    assert r.status_code == 201, r.text
    claim_id = r.json()["data"]["id"]
    assert client.post(f"/api/v1/claims/{claim_id}/runs", json={}, headers=summ).status_code == 400  # no documents yet

    files = [("files", (n, d, "application/octet-stream")) for n, d, _ in build_files()]
    r = client.post(f"/api/v1/claims/{claim_id}/documents", files=files, data={"source_channel": "fax"}, headers=summ)
    assert r.status_code == 201 and len(r.json()["data"]) == 9
    r = client.post(f"/api/v1/claims/{claim_id}/documents", files=[("files", ("evil.exe", b"MZ\x90\x00binary", "application/octet-stream"))], headers=summ)
    assert r.status_code == 400  # MIME sniffing rejects unsupported types

    r = client.post(f"/api/v1/claims/{claim_id}/runs", json={"mode": "full"}, headers=summ)
    assert r.status_code == 202
    run_id = r.json()["data"]["run_id"]
    assert client.post(f"/api/v1/claims/{claim_id}/runs", json={}, headers=summ).status_code == 409
    drain()

    # HITL-0: employer conflict (Meridian vs Keystone) must be confirmed by the examiner
    rv = pending_review(client, examiner, claim_id, "HITL-0")
    assert any(c["field"] == "employer_name" for c in rv["payload"]["conflicts"])
    assert client.post(f"/api/v1/reviews/{rv['id']}/submit", json={}, headers=ncm).status_code == 403
    r = client.post(f"/api/v1/reviews/{rv['id']}/submit", json={"fields": {"employer_name": "Keystone Industrial Services"}}, headers=examiner)
    assert r.status_code == 202, r.text
    drain()

    # HITL-1: NCM timeline check; duplicates and fax covers removed, missing MRI report detected
    rv = pending_review(client, ncm, claim_id, "HITL-1")
    removed = {d["status"] for d in rv["payload"]["removed_documents"]}
    assert {"duplicate", "noise"} <= removed
    assert any("MRI" in g["description"] for g in rv["payload"]["gaps"])
    tl = client.get(f"/api/v1/claims/{claim_id}/timeline", headers=ncm).json()["data"]
    assert len(tl["episodes"]) >= 6
    assert client.post(f"/api/v1/reviews/{rv['id']}/submit", json={"decision": "approve"}, headers=ncm).status_code == 202
    drain()

    # HITL-2: clinical reviewer validates milestone facts against the source (side-by-side)
    rv = pending_review(client, reviewer, claim_id, "HITL-2")
    facts = rv["payload"]["facts"]
    assert facts and all(f["citations"] for f in facts)
    assert client.post(f"/api/v1/reviews/{rv['id']}/submit", json={}, headers=reviewer).status_code == 400  # facts not actioned
    first = facts[0]
    r = client.patch(f"/api/v1/facts/{first['id']}", json={"action": "edit", "value": first["value"]}, headers=reviewer)
    assert r.status_code == 400  # edits require a reason
    r = client.patch(f"/api/v1/facts/{first['id']}", json={"action": "edit", "value": first["value"], "reason": "Normalised wording"}, headers=reviewer)
    assert r.status_code == 200 and r.json()["data"]["validation_status"] == "edited"
    rest = [f["id"] for f in facts[1:]]
    assert client.post("/api/v1/facts/bulk-action", json={"fact_ids": rest, "action": "accept"}, headers=reviewer).status_code == 200
    for d in rv["payload"]["discrepancies"]:
        client.patch(f"/api/v1/discrepancies/{d['id']}", json={"resolution": "Verified against source"}, headers=reviewer)
    assert client.post(f"/api/v1/reviews/{rv['id']}/submit", json={}, headers=reviewer).status_code == 202
    drain()

    # Stage 5 findings: PT visits, opioid duration and stalled recovery flagged with rule citations
    findings = client.get(f"/api/v1/claims/{claim_id}/guideline-findings", headers=reviewer).json()["data"]
    types = {f["finding_type"] for f in findings}
    assert {"excessive_duration", "off_guideline_request", "stalled_recovery"} <= types
    assert all(f["rule"] for f in findings if f["finding_type"] != "no_applicable_guideline")

    # HITL-3: NCM edits then approves the one-page summary
    rv = pending_review(client, ncm, claim_id, "HITL-3")
    one_id = rv["payload"]["summaries"]["one_page"]["id"]
    s = client.get(f"/api/v1/summaries/{one_id}", headers=ncm).json()["data"]
    assert s["word_count"] <= 600 and "[[cite:" in s["content_md"]
    r = client.put(f"/api/v1/summaries/{one_id}", json={"content_md": s["content_md"] + "\n\n### NCM note\n- Employer cannot accommodate light duty.", "reason": "context"}, headers=ncm)
    assert r.status_code == 200 and r.json()["data"]["version"] == s["version"] + 1
    assert client.post(f"/api/v1/reviews/{rv['id']}/submit", json={"action": "approve"}, headers=ncm).status_code == 202
    drain()

    # HITL-4: one-click flag approvals (override needs a reason) + decision; UR determination in parallel
    rv = pending_review(client, examiner, claim_id, "HITL-4")
    flags = [f for f in rv["payload"]["flags"] if f["flag_type"] in ("mmi_status", "rtw_limit", "guideline_deviation")]
    assert client.post(f"/api/v1/flags/{flags[0]['id']}/action", json={"action": "reject"}, headers=examiner).status_code == 400
    for f in flags:
        assert client.post(f"/api/v1/flags/{f['id']}/action", json={"action": "approve"}, headers=examiner).status_code == 200
    ur = pending_review(client, reviewer, claim_id, "HITL-4-UR")
    ua_ids = [u["id"] for u in ur["payload"]["utilization_assessments"]]
    det = {"utilization_assessment_id": ua_ids[0], "determination": "non_certified",
           "clinical_rationale": "24 visits completed exceed the guideline maximum with no functional gain; FCE recommends work hardening."}
    assert client.post(f"/api/v1/claims/{claim_id}/ur-determinations", json=det, headers=examiner).status_code == 403  # UR = clinical reviewer only
    assert client.post(f"/api/v1/claims/{claim_id}/ur-determinations", json=det, headers=reviewer).status_code == 201
    decision = {"decisions": [{"decision_type": "treatment_authorization", "outcome": "Deny additional PT; authorize 4-week work hardening",
                               "rationale": "Guideline visit maximum exceeded with plateau; FCE light capacity vs medium job.",
                               "next_steps": ["Diary MMI re-evaluation 06/2025"]}]}
    assert client.post(f"/api/v1/reviews/{rv['id']}/submit", json=decision, headers=examiner).status_code == 202
    drain()

    # HITL-5: high-risk claim -> supervisor sign-off; the deciding user cannot sign off (SoD)
    run = client.get(f"/api/v1/runs/{run_id}", headers=supervisor).json()["data"]
    assert run["status"] == "awaiting_human" and run["pending_review"]["checkpoint"] == "HITL-5"
    rv = pending_review(client, supervisor, claim_id, "HITL-5")
    assert client.post(f"/api/v1/reviews/{rv['id']}/submit", json={"action": "signoff", "comments": "ok"}, headers=examiner).status_code == 403
    assert client.post(f"/api/v1/reviews/{rv['id']}/submit", json={"action": "signoff", "comments": "Reviewed and approved"}, headers=supervisor).status_code == 202
    drain()

    run = client.get(f"/api/v1/runs/{run_id}", headers=supervisor).json()["data"]
    assert run["status"] == "completed", run
    decisions = client.get(f"/api/v1/claims/{claim_id}/decisions", headers=supervisor).json()["data"]["decisions"]
    assert decisions[0]["status"] == "sealed" and decisions[0]["record_hash"] and decisions[0]["signed_off_by"]

    # approved reports are exportable; attorney sees only approved content after being granted access
    reports = client.get(f"/api/v1/claims/{claim_id}/reports", headers=supervisor).json()["data"]
    assert {r["report_type"] for r in reports} >= {"one_page_summary", "mmi_status", "medical_chronology", "decision_provenance"}
    rid = next(r["id"] for r in reports if r["report_type"] == "one_page_summary")
    pdf = client.get(f"/api/v1/reports/{rid}/download", headers=supervisor)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    attorney = login(client, "attorney@claims.example")
    assert client.get(f"/api/v1/claims/{claim_id}", headers=attorney).status_code == 403
    att_id = next(u["id"] for u in client.get("/api/v1/users", headers=supervisor).json()["data"] if u["full_name"].startswith("Alex"))
    assert client.post(f"/api/v1/claims/{claim_id}/members", json={"user_id": att_id, "role_key": "attorney"}, headers=supervisor).status_code == 201
    assert client.get(f"/api/v1/claims/{claim_id}/chronology", headers=attorney).status_code == 200
    assert client.get(f"/api/v1/claims/{claim_id}/dashboard", headers=attorney).status_code == 403
    assert any(r["id"] == rid for r in client.get("/api/v1/reports", headers=attorney).json()["data"])

    # export job, search, SSE replay, audit + hash chain, CMS outbox
    r = client.post(f"/api/v1/claims/{claim_id}/reports", json={"report_type": "medical_chronology", "format": "docx"}, headers=summ)
    drain()
    rep = client.get(f"/api/v1/reports/{r.json()['data']['report_id']}", headers=summ).json()["data"]
    assert rep["status"] == "ready"
    hits = client.get(f"/api/v1/claims/{claim_id}/search", params={"q": "microdiscectomy L4-L5", "mode": "hybrid"}, headers=ncm).json()["data"]
    assert hits and hits[0]["page_number"] >= 1
    with client.stream("GET", f"/api/v1/runs/{run_id}/events", headers=summ) as s:
        text = "".join(chunk for chunk in s.iter_text())
    assert "event: run_completed" in text and "event: awaiting_review" in text
    assert client.get("/api/v1/audit/verify", headers=supervisor).json()["data"]["valid"]
    trail = client.get(f"/api/v1/claims/{claim_id}/audit", params={"page_size": 500}, headers=supervisor).json()["data"]
    actions = {a["action"] for a in trail}
    assert {"document.upload", "fact.edit", "flag.approve", "decision.create", "decision.signoff", "decision.seal", "cms.sync",
            "phi.view", "report.export"} <= actions
    metrics = client.get("/api/v1/metrics/summary", headers=supervisor).json()["data"]
    assert metrics["business"]["pages_processed"] > 0
