"""Phase 3.10 — RBAC, audit chain integrity, ACS confirmation, model router."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest


def _make_je(amount="100.00", entry_id="JE-SEC-001", status="APPROVED"):
    from backend.models.schemas import JournalEntry, JournalEntryLine, JEStatus
    amt = Decimal(amount)
    return JournalEntry(
        entry_id=entry_id, church_id="testch",
        fiscal_year=2026, accounting_period="2026-05",
        entry_date=date(2026, 5, 6), reference="INV",
        vendor_name="Test", description="Sec test",
        status=JEStatus(status),
        lines=[
            JournalEntryLine(
                sequence=1, account_number="7100", account_name="Office",
                fund_id="GEN", fund_name="General",
                debit=amt, credit=Decimal("0"), memo="x",
            ),
            JournalEntryLine(
                sequence=2, account_number="2010", account_name="AP",
                fund_id="GEN", fund_name="General",
                debit=Decimal("0"), credit=amt, memo="x",
            ),
        ],
        total_debits=amt, total_credits=amt, balanced=True,
    )


# =====================================================================
# RBAC
# =====================================================================

def test_has_role_precedence():
    from backend.auth import has_role
    assert has_role("TREASURER_ADMIN", "FINANCE_STAFF") is True
    assert has_role("TREASURER_ADMIN", "BUDGET_OWNER") is True
    assert has_role("TREASURER_ADMIN", "TREASURER_ADMIN") is True
    assert has_role("FINANCE_STAFF", "TREASURER_ADMIN") is False
    assert has_role("BUDGET_OWNER", "TREASURER_ADMIN") is False
    assert has_role(None, "FINANCE_STAFF") is False


def test_finance_staff_cannot_post_je(tmp_path, monkeypatch):
    """A FINANCE_STAFF user must get 403 when posting a JE."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    monkeypatch.setattr(main_mod, "JE_DATA_DIR", tmp_path)
    je = _make_je(entry_id="JE-RBAC-1")
    main_mod._persist_je("testch", je.model_dump())

    client = TestClient(main_mod.app)
    r = client.post(
        f"/api/jes/{je.entry_id}/post",
        json={"confirmed": True},
        headers={"X-User-Role": "FINANCE_STAFF"},
    )
    assert r.status_code == 403, r.text
    assert "lacks" in r.json().get("detail", "")


def test_treasurer_can_pass_rbac_for_post(tmp_path, monkeypatch):
    """A TREASURER_ADMIN passes RBAC. (Endpoint may still fail downstream
    due to no real ACS, but it should not return 403.)"""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    monkeypatch.setattr(main_mod, "JE_DATA_DIR", tmp_path)
    je = _make_je(entry_id="JE-RBAC-2")
    main_mod._persist_je("testch", je.model_dump())

    client = TestClient(main_mod.app)
    r = client.post(
        f"/api/jes/{je.entry_id}/post",
        json={"confirmed": True},
        headers={"X-User-Role": "TREASURER_ADMIN"},
    )
    # 403 must not happen; could be 200/500 depending on ACS mock.
    assert r.status_code != 403, r.text


# =====================================================================
# ACS confirmation gate
# =====================================================================

def test_post_without_confirmed_returns_428(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    monkeypatch.setattr(main_mod, "JE_DATA_DIR", tmp_path)
    je = _make_je(entry_id="JE-CONF-1")
    main_mod._persist_je("testch", je.model_dump())

    client = TestClient(main_mod.app)
    r = client.post(
        f"/api/jes/{je.entry_id}/post",
        json={},  # no confirmed flag
        headers={"X-User-Role": "TREASURER_ADMIN"},
    )
    assert r.status_code == 428, r.text
    # JE status should remain APPROVED (no transition).
    je2, _ = main_mod._find_journal_entry(je.entry_id)
    assert je2 is not None
    assert je2.status.value == "APPROVED"


# =====================================================================
# Audit chain integrity
# =====================================================================

def test_audit_chain_verify_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main as main_mod
    from backend.tools import approval_audit

    # Redirect audit dir to temp for isolation
    monkeypatch.setattr(
        approval_audit, "AUDIT_DIR",
        tmp_path / "audits", raising=False,
    )
    # Force re-resolution of audit dir if module computed it lazily
    # by writing into the actual configured path:
    from backend.tools.approval_audit import append_event, verify_chain
    cid = "audtest"
    append_event(cid, {"event_type": "TEST", "msg": "hello"})
    append_event(cid, {"event_type": "TEST", "msg": "world"})
    assert verify_chain(cid) is True

    client = TestClient(main_mod.app)
    r = client.get("/api/audit-chain/verify", params={"church_id": cid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True


def test_audit_chain_detects_tampering(tmp_path, monkeypatch):
    """If we tamper with a row's hash, verify_chain returns False."""
    from backend.tools.approval_audit import (
        append_event, verify_chain, _store_path,
    )
    cid = f"tamper_{datetime.utcnow().strftime('%H%M%S')}"
    append_event(cid, {"event_type": "A"})
    append_event(cid, {"event_type": "B"})
    assert verify_chain(cid) is True

    # Tamper: rewrite second line with bogus hash
    p = _store_path(cid)
    lines = p.read_text().splitlines()
    assert len(lines) >= 2
    row = json.loads(lines[1])
    row["hash"] = "tampered"
    lines[1] = json.dumps(row)
    p.write_text("\n".join(lines) + "\n")

    assert verify_chain(cid) is False
    # Cleanup tamper file
    if p.exists():
        p.unlink()


# =====================================================================
# Model router
# =====================================================================

def test_model_router_default():
    from backend.tools.model_router import resolve_model
    # Defaults exist for known agents
    m = resolve_model("gl_classifier")
    assert isinstance(m, str) and len(m) > 0


def test_model_router_save_and_resolve(tmp_path, monkeypatch):
    from backend.tools import model_router
    monkeypatch.setattr(
        model_router, "_CONFIG_PATH", tmp_path / "model_config.json",
    )
    out = model_router.save_model_config({"gl_classifier": "claude-haiku-test"})
    assert out["gl_classifier"] == "claude-haiku-test"
    assert model_router.resolve_model("gl_classifier") == "claude-haiku-test"
    # Untouched agents still default
    assert model_router.resolve_model("treasurer_chat") != "claude-haiku-test"


def test_model_config_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main as main_mod
    from backend.tools import model_router

    monkeypatch.setattr(
        model_router, "_CONFIG_PATH", tmp_path / "model_config.json",
    )
    client = TestClient(main_mod.app)

    r = client.get("/api/model-config")
    assert r.status_code == 200
    cfg = r.json()
    assert "gl_classifier" in cfg

    r2 = client.put(
        "/api/model-config",
        json={"gl_classifier": "claude-haiku"},
        headers={"X-User-Role": "TREASURER_ADMIN"},
    )
    assert r2.status_code == 200
    assert r2.json()["gl_classifier"] == "claude-haiku"

    r3 = client.get("/api/model-config/gl_classifier")
    assert r3.status_code == 200
    assert r3.json()["model"] == "claude-haiku"


# =====================================================================
# Phase 3.10 hardening: RBAC fully wired across remaining sensitive endpoints
# =====================================================================

def test_finance_staff_cannot_approve_payment(tmp_path, monkeypatch):
    """FR-4.1: FINANCE_STAFF must be 403 when calling /payments/{id}/approve."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    client = TestClient(main_mod.app)
    r = client.post(
        "/api/payments/PMT-DOES-NOT-EXIST/approve",
        json={"approver_email": "f@x.org"},
        headers={"X-User-Role": "FINANCE_STAFF"},
    )
    assert r.status_code == 403, r.text
    assert "lacks" in r.json().get("detail", "").lower() or "treasurer" in r.json().get("detail", "").lower()


def test_finance_staff_cannot_reset_ytd(tmp_path, monkeypatch):
    """FR-4.1: YTD reset is TREASURER_ADMIN-only."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    client = TestClient(main_mod.app)
    r = client.put(
        "/api/churches/testch/budget/ytd-reset",
        json={"confirm": True, "reset_to_zero": True},
        headers={"X-User-Role": "FINANCE_STAFF"},
    )
    assert r.status_code == 403, r.text


def test_budget_owner_cannot_reset_ytd(monkeypatch):
    """BUDGET_OWNER must NOT be able to reset YTD (treasurer-only)."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    client = TestClient(main_mod.app)
    r = client.put(
        "/api/churches/testch/budget/ytd-reset",
        json={"confirm": True, "reset_to_zero": True},
        headers={"X-User-Role": "BUDGET_OWNER"},
    )
    assert r.status_code == 403, r.text


def test_finance_staff_cannot_modify_approval_chains():
    """FR-4.1: PUT/POST/DELETE /approval-chains require TREASURER_ADMIN."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    client = TestClient(main_mod.app)
    r = client.put(
        "/api/churches/testch/approval-chains",
        json=[],
        headers={"X-User-Role": "FINANCE_STAFF"},
    )
    assert r.status_code == 403, r.text


def test_finance_staff_cannot_make_treasurer_decision():
    """FR-4.1: /jobs/{id}/treasurer-decision requires TREASURER_ADMIN."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    client = TestClient(main_mod.app)
    r = client.post(
        "/api/jobs/JOB-NONEXISTENT/treasurer-decision",
        json={"action": "APPROVE", "treasurer_id": "t@x.org"},
        headers={"X-User-Role": "FINANCE_STAFF"},
    )
    # Must be 403, not 404 - RBAC checks before resource lookup
    assert r.status_code == 403, r.text


def test_finance_staff_cannot_modify_model_config():
    """FR-4.4: PUT /model-config requires TREASURER_ADMIN."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    client = TestClient(main_mod.app)
    r = client.put(
        "/api/model-config",
        json={"gl_classifier": "evil-model"},
        headers={"X-User-Role": "FINANCE_STAFF"},
    )
    assert r.status_code == 403, r.text


def test_finance_staff_can_read_model_config():
    """Read-only model config should be accessible to all roles."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    client = TestClient(main_mod.app)
    r = client.get(
        "/api/model-config",
        headers={"X-User-Role": "FINANCE_STAFF"},
    )
    assert r.status_code == 200, r.text


def test_finance_staff_can_read_audit_chain():
    """Verify endpoint should be readable by all roles for transparency."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    client = TestClient(main_mod.app)
    r = client.get(
        "/api/audit-chain/verify",
        params={"church_id": "testch"},
        headers={"X-User-Role": "FINANCE_STAFF"},
    )
    assert r.status_code == 200, r.text


def test_audit_event_includes_required_fields(tmp_path, monkeypatch):
    """Audit events must contain timestamp, event_id, prev_hash, hash."""
    from backend.tools.approval_audit import append_event, _store_path
    cid = f"fields_{datetime.utcnow().strftime('%H%M%S%f')}"
    row = append_event(cid, {"event_type": "TEST_EVT", "actor": "x@y.org"})
    assert "event_id" in row
    assert "timestamp" in row
    assert "prev_hash" in row
    assert "hash" in row
    assert row["prev_hash"] == "GENESIS"  # First row
    # Cleanup
    p = _store_path(cid)
    if p.exists():
        p.unlink()


def test_audit_chain_genesis_handling():
    """First event has prev_hash=GENESIS; second has prev_hash==first's hash."""
    from backend.tools.approval_audit import append_event, _store_path
    cid = f"genesis_{datetime.utcnow().strftime('%H%M%S%f')}"
    r1 = append_event(cid, {"event_type": "FIRST"})
    r2 = append_event(cid, {"event_type": "SECOND"})
    assert r1["prev_hash"] == "GENESIS"
    assert r2["prev_hash"] == r1["hash"]
    # Cleanup
    p = _store_path(cid)
    if p.exists():
        p.unlink()


def test_model_router_resolves_unknown_agent_default():
    """Unknown agent names should fall back to env-based default, not raise."""
    from backend.tools.model_router import resolve_model
    out = resolve_model("totally_made_up_agent_xyz")
    assert isinstance(out, str) and len(out) > 0


def test_jes_html_has_acs_confirmation_modal():
    """FR-NF: jes.html must include the ACS confirmation gate modal with
    a checkbox attestation, not a bare confirm() dialog."""
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / "frontend" / "jes.html"
    html = p.read_text()
    assert 'id="acs-confirm-modal"' in html
    assert 'id="acs-confirm-checkbox"' in html
    assert 'id="acs-confirm-btn"' in html
    assert 'cannot be undone' in html
    # The modal helper function must exist
    assert 'openAcsConfirmModal' in html


def test_model_config_html_page_exists():
    """FR-NF: model-config.html settings page must exist for admin model overrides."""
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / "frontend" / "settings" / "model-config.html"
    assert p.exists(), "model-config.html settings page is missing"
    html = p.read_text()
    assert 'Model Configuration' in html
    assert '/api/model-config' in html
    # Must send admin header on PUT
    assert 'TREASURER_ADMIN' in html or 'ADMIN' in html


def test_treasurer_can_modify_model_config(tmp_path, monkeypatch):
    """TREASURER_ADMIN must be able to update model overrides."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod
    from backend.tools import model_router

    monkeypatch.setattr(
        model_router, "_CONFIG_PATH", tmp_path / "model_config.json",
    )
    client = TestClient(main_mod.app)
    r = client.put(
        "/api/model-config",
        json={"gl_classifier": "claude-treasurer-set"},
        headers={"X-User-Role": "TREASURER_ADMIN"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["gl_classifier"] == "claude-treasurer-set"
