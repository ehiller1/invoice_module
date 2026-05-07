"""Phase 2 (FR-05) approval-chain, token, audit, and treasurer-gate tests."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from backend.models.schemas import (
    ApprovalChain,
    DocumentType,
    ProcessingJob,
    ProcessingStatus,
)


# ---------- Fixtures: redirect data dirs to tmp_path ----------

@pytest.fixture(autouse=True)
def _isolate_data(monkeypatch, tmp_path):
    """Redirect approval-chain / token / audit storage into tmp_path so tests
    don't pollute the real data dir."""
    from backend.tools import approval_chain_resolver, approval_audit
    from backend.integrations.email import tokens as email_tokens

    monkeypatch.setattr(approval_chain_resolver, "DATA_DIR", tmp_path)
    monkeypatch.setattr(approval_audit, "DATA_DIR", tmp_path)
    monkeypatch.setattr(email_tokens, "TOKEN_STORE", tmp_path / "tokens.json")
    yield


def _chain(chain_id: str, pattern: str) -> ApprovalChain:
    return ApprovalChain(
        chain_id=chain_id,
        gl_pattern=pattern,
        primary_approver_email="owner@example.org",
        primary_approver_name="Owner",
        secondary_approver_email="treasurer@example.org",
        secondary_approver_name="Treasurer",
        deadline_hours=48,
        escalation_days=5,
        active=True,
    )


# ---------- 2.1 pattern matching ----------

def test_approval_chain_pattern_matches_exact():
    from backend.tools import approval_chain_resolver as r
    r.save_chains("c1", [_chain("c1", "6500")])
    assert r.find_chain_for_gl("c1", "6500") is not None
    assert r.find_chain_for_gl("c1", "6501") is None


def test_approval_chain_pattern_matches_wildcard():
    from backend.tools import approval_chain_resolver as r
    r.save_chains("c1", [_chain("c1", "65*")])
    assert r.find_chain_for_gl("c1", "6500") is not None
    assert r.find_chain_for_gl("c1", "6599") is not None
    assert r.find_chain_for_gl("c1", "7100") is None


def test_approval_chain_pattern_matches_range():
    from backend.tools import approval_chain_resolver as r
    r.save_chains("c1", [_chain("c1", "6500-6600")])
    assert r.find_chain_for_gl("c1", "6500") is not None
    assert r.find_chain_for_gl("c1", "6550") is not None
    assert r.find_chain_for_gl("c1", "6600") is not None
    assert r.find_chain_for_gl("c1", "6499") is None
    assert r.find_chain_for_gl("c1", "6601") is None


def test_resolution_order_exact_then_range_then_wildcard():
    from backend.tools import approval_chain_resolver as r
    r.save_chains("c1", [
        _chain("wild", "65*"),
        _chain("rng", "6500-6510"),
        _chain("exact", "6505"),
    ])
    # Exact wins.
    assert r.find_chain_for_gl("c1", "6505").chain_id == "exact"
    # Range wins over wildcard for accounts in range but not the exact.
    assert r.find_chain_for_gl("c1", "6502").chain_id == "rng"
    # Wildcard catches accounts outside the range.
    assert r.find_chain_for_gl("c1", "6555").chain_id == "wild"


# ---------- 2.2 tokens ----------

def test_token_mint_and_consume_roundtrip():
    from backend.integrations.email import tokens as t
    tok = t.mint("APPROVE", {"job_id": "j1"}, "budget_owner", ttl_seconds=60)
    assert tok and len(tok) > 20
    claims = t.consume(tok)
    assert claims is not None
    assert claims["action"] == "APPROVE"
    assert claims["context"]["job_id"] == "j1"


def test_token_cannot_be_consumed_twice():
    from backend.integrations.email import tokens as t
    tok = t.mint("APPROVE", {}, "budget_owner", ttl_seconds=60)
    assert t.consume(tok) is not None
    assert t.consume(tok) is None


def test_token_expires_after_ttl():
    from backend.integrations.email import tokens as t
    tok = t.mint("APPROVE", {}, "budget_owner", ttl_seconds=1)
    time.sleep(1.1)
    assert t.consume(tok) is None


def test_token_unknown_returns_none():
    from backend.integrations.email import tokens as t
    assert t.consume("not-a-real-token") is None
    assert t.consume("") is None


# ---------- 2.4 audit chain ----------

def test_audit_chain_hash_integrity():
    from backend.tools import approval_audit
    approval_audit.append_event("c1", {"job_id": "j1", "action": "APPROVE", "actor_email": "a@x"})
    approval_audit.append_event("c1", {"job_id": "j1", "action": "APPROVE", "actor_email": "b@x"})
    approval_audit.append_event("c1", {"job_id": "j1", "action": "REJECT", "actor_email": "c@x"})
    assert approval_audit.verify_chain("c1") is True
    rows = approval_audit.list_events("c1")
    assert len(rows) == 3
    assert rows[0]["prev_hash"] == approval_audit.GENESIS_HASH
    # Each row's prev_hash matches prior row's hash.
    for i in range(1, len(rows)):
        assert rows[i]["prev_hash"] == rows[i-1]["hash"]


def test_audit_chain_detects_tampering(tmp_path):
    from backend.tools import approval_audit
    approval_audit.append_event("c2", {"job_id": "j1", "action": "APPROVE"})
    approval_audit.append_event("c2", {"job_id": "j1", "action": "APPROVE"})
    p = approval_audit._store_path("c2")
    # Mutate the first row's `action` field to APPROVED_TAMPERED.
    lines = p.read_text().splitlines()
    row = json.loads(lines[0])
    row["action"] = "APPROVED_TAMPERED"
    lines[0] = json.dumps(row)
    p.write_text("\n".join(lines) + "\n")
    assert approval_audit.verify_chain("c2") is False


def test_audit_filter_by_job_id():
    from backend.tools import approval_audit
    approval_audit.append_event("c3", {"job_id": "A", "action": "X"})
    approval_audit.append_event("c3", {"job_id": "B", "action": "Y"})
    approval_audit.append_event("c3", {"job_id": "A", "action": "Z"})
    rows = approval_audit.list_events("c3", job_id="A")
    assert len(rows) == 2
    assert all(r["job_id"] == "A" for r in rows)


# ---------- 2.3 treasurer endpoint ----------

def test_treasurer_endpoint_only_allows_pending_treasurer(monkeypatch):
    """POST /api/jobs/{id}/treasurer-decision must reject non-PENDING_TREASURER."""
    from fastapi.testclient import TestClient
    from backend import flow
    from backend import main as main_mod

    client = TestClient(main_mod.app)

    # Create a job in the in-memory store with a non-PENDING_TREASURER status.
    job = ProcessingJob(
        job_id="job_test_1",
        church_id="c1",
        filename="x.pdf",
        pdf_path="/tmp/x.pdf",
        document_type=DocumentType.INVOICE,
        status=ProcessingStatus.UPLOADED,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    flow._jobs[job.job_id] = job
    try:
        r = client.post(
            f"/api/jobs/{job.job_id}/treasurer-decision",
            json={"action": "approve", "treasurer_id": "t@x", "notes": ""},
        )
        assert r.status_code == 400

        # Now flip to PENDING_TREASURER and retry — should succeed.
        job.status = ProcessingStatus.PENDING_TREASURER
        r2 = client.post(
            f"/api/jobs/{job.job_id}/treasurer-decision",
            json={"action": "approve", "treasurer_id": "t@x", "notes": ""},
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["ok"] is True
    finally:
        flow._jobs.pop(job.job_id, None)


def test_treasurer_endpoint_unknown_job_returns_404():
    from fastapi.testclient import TestClient
    from backend import main as main_mod
    client = TestClient(main_mod.app)
    r = client.post(
        "/api/jobs/does-not-exist/treasurer-decision",
        json={"action": "approve", "treasurer_id": "t", "notes": ""},
    )
    assert r.status_code == 404
