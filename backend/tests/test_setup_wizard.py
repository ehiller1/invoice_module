"""Tests for EIME Setup Wizard endpoints.

The setup wizard guides new users through:
  1. Church profile creation
  2. Chart of accounts import
  3. Plaid credentials
  4. ACS Realm credentials
  5. SMTP email config
  6. User accounts (with roles)
  7. Approval chains
  8. Budget import (optional)
  9. Final completion / status flag

Tests use a tmp data dir to isolate from real church data.
"""
from __future__ import annotations
import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------- Fixtures ----------

@pytest.fixture
def tmp_setup_root(tmp_path, monkeypatch):
    """Redirect SETUP_DIR + coa_store.DATA_ROOT into a tmp dir."""
    from backend.tools import coa_store
    new_root = tmp_path / "data"
    new_root.mkdir()
    new_chroma = new_root / "chroma"
    new_chroma.mkdir()

    monkeypatch.setattr(coa_store, "DATA_ROOT", new_root)
    monkeypatch.setattr(coa_store, "CHROMA_DIR", new_chroma)
    monkeypatch.setattr(coa_store, "_chroma_client", None)
    monkeypatch.setattr(coa_store, "_rebuild_index", lambda ctx: None)

    # Patch the wizard module's SETUP_DIR
    from backend import setup_wizard
    monkeypatch.setattr(setup_wizard, "SETUP_DIR", new_root)
    yield new_root


@pytest.fixture
def client(tmp_setup_root):
    from backend.main import app
    return TestClient(app)


def _make_csv_bytes(rows: list[list[str]]) -> bytes:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


# ---------- Tests ----------

def test_wizard_endpoints_exist(client):
    """All 9 setup wizard endpoints are registered."""
    routes = [r.path for r in client.app.routes]
    assert "/api/setup/status" in routes
    assert "/api/setup/church-profile" in routes
    assert "/api/setup/coa-import" in routes
    assert "/api/setup/plaid-test" in routes
    assert "/api/setup/acs-test" in routes
    assert "/api/setup/smtp-test" in routes
    assert "/api/setup/users" in routes
    assert "/api/setup/approval-chains" in routes
    assert "/api/setup/budget-import" in routes
    assert "/api/setup/complete" in routes


def test_setup_status_endpoint(client, tmp_setup_root):
    """Status returns False until .setup_complete marker exists."""
    r = client.get("/api/setup/status")
    assert r.status_code == 200
    assert r.json()["setup_complete"] is False

    # Create the marker
    (tmp_setup_root / ".setup_complete").write_text("done")
    r = client.get("/api/setup/status")
    assert r.json()["setup_complete"] is True


def test_church_profile_saved(client, tmp_setup_root):
    """POST /church-profile creates a church_profile_{id}.json file."""
    body = {
        "church_id": "testch",
        "church_name": "Test Church",
        "denomination": "EPISCOPAL",
        "fiscal_year_start": "2025-01-01",
        "address": "123 Main St",
    }
    r = client.post("/api/setup/church-profile", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["church_id"] == "testch"
    assert data["status"] in ("ok", "created")
    profile = tmp_setup_root / "church_profile_testch.json"
    assert profile.exists()
    saved = json.loads(profile.read_text())
    assert saved["church_name"] == "Test Church"
    assert saved["denomination"] == "EPISCOPAL"


def test_church_profile_validates_required_fields(client):
    """Missing church_name -> 422."""
    body = {"church_id": "testch", "denomination": "EPISCOPAL"}
    r = client.post("/api/setup/church-profile", json=body)
    assert r.status_code in (400, 422)


def test_coa_import_parses_spreadsheet(client, tmp_setup_root):
    """COA import parses a CSV and reports account_count."""
    # Seed church first
    client.post("/api/setup/church-profile", json={
        "church_id": "testch",
        "church_name": "Test Church",
        "denomination": "EPISCOPAL",
        "fiscal_year_start": "2025-01-01",
    })
    csv = _make_csv_bytes([
        ["account_number", "account_name", "account_type", "fund"],
        ["1000", "Cash", "Asset", "GEN"],
        ["4000", "Tithes", "Revenue", "GEN"],
        ["5000", "Salaries", "Expense", "GEN"],
    ])
    r = client.post(
        "/api/setup/coa-import?church_id=testch",
        files={"file": ("coa.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["account_count"] >= 3
    assert data["imported"] is True


def test_plaid_test_validates_credentials(client):
    """plaid-test returns success on mocked happy path."""
    with patch("backend.setup_wizard._plaid_create_link_token") as mock:
        mock.return_value = {"link_token": "link-sandbox-abc"}
        r = client.post("/api/setup/plaid-test", json={
            "client_id": "abc123",
            "secret": "shh",
            "env": "sandbox",
        })
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True


def test_plaid_test_failure(client):
    """plaid-test returns success=False on error."""
    with patch("backend.setup_wizard._plaid_create_link_token") as mock:
        mock.side_effect = Exception("invalid_client_id")
        r = client.post("/api/setup/plaid-test", json={
            "client_id": "x",
            "secret": "y",
            "env": "sandbox",
        })
    assert r.status_code == 200
    assert r.json()["success"] is False
    assert "invalid_client_id" in r.json()["message"]


def test_acs_test_validates_login(client):
    """acs-test returns success when login succeeds."""
    with patch("backend.setup_wizard._acs_login") as mock:
        mock.return_value = True
        r = client.post("/api/setup/acs-test", json={
            "username": "alice",
            "password": "pw",
            "base_url": "https://realm.acsedu.org",
        })
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_smtp_test_sends_email(client):
    """smtp-test posts to SMTP and returns success."""
    with patch("backend.setup_wizard._smtp_send_test") as mock:
        mock.return_value = True
        r = client.post("/api/setup/smtp-test", json={
            "from_email": "noreply@church.org",
            "smtp_host": "smtp.sendgrid.net",
            "smtp_port": 587,
            "username": "apikey",
            "password": "SG.test",
        })
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_users_created_with_roles(client, tmp_setup_root):
    """Users endpoint persists user list to users_{church}.json."""
    body = {
        "church_id": "testch",
        "users": [
            {"name": "Alice", "email": "alice@church.org", "role": "TREASURER_ADMIN"},
            {"name": "Bob", "email": "bob@church.org", "role": "BUDGET_OWNER"},
        ],
    }
    r = client.post("/api/setup/users", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created_count"] == 2
    f = tmp_setup_root / "users_testch.json"
    assert f.exists()
    saved = json.loads(f.read_text())
    emails = [u["email"] for u in saved["users"]]
    assert "alice@church.org" in emails


def test_users_email_validation(client):
    """Invalid email returns 400."""
    body = {
        "church_id": "testch",
        "users": [{"name": "Bad", "email": "not-an-email", "role": "TREASURER_ADMIN"}],
    }
    r = client.post("/api/setup/users", json=body)
    assert r.status_code in (400, 422)


def test_approval_chains_created(client, tmp_setup_root):
    """Approval chain endpoint persists chains to file."""
    body = {
        "church_id": "testch",
        "chains": [
            {
                "gl_pattern": "6000-6999",
                "primary_email": "alice@church.org",
                "secondary_email": "bob@church.org",
                "deadline_hours": 48,
            },
            {
                "gl_pattern": "7*",
                "primary_email": "alice@church.org",
                "secondary_email": None,
                "deadline_hours": 24,
            },
        ],
    }
    r = client.post("/api/setup/approval-chains", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created_count"] == 2
    f = tmp_setup_root / "approval_chains_testch.json"
    assert f.exists()


def test_budget_import_optional(client, tmp_setup_root):
    """Budget import is optional and parses spreadsheet."""
    # Need a church with COA first
    client.post("/api/setup/church-profile", json={
        "church_id": "testch",
        "church_name": "Test Church",
        "denomination": "EPISCOPAL",
        "fiscal_year_start": "2025-01-01",
    })
    coa_csv = _make_csv_bytes([
        ["account_number", "account_name", "account_type", "fund"],
        ["5000", "Salaries", "Expense", "GEN"],
    ])
    client.post(
        "/api/setup/coa-import?church_id=testch",
        files={"file": ("coa.csv", coa_csv, "text/csv")},
    )

    budget_csv = _make_csv_bytes([
        ["account_number", "annual_budget"],
        ["5000", "120000"],
    ])
    r = client.post(
        "/api/setup/budget-import?church_id=testch",
        files={"file": ("budget.csv", budget_csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True


def test_setup_complete_returns_success(client, tmp_setup_root):
    """Complete endpoint sets marker and returns next_url."""
    # Seed required state
    client.post("/api/setup/church-profile", json={
        "church_id": "testch",
        "church_name": "Test Church",
        "denomination": "EPISCOPAL",
        "fiscal_year_start": "2025-01-01",
    })
    r = client.post("/api/setup/complete", json={"church_id": "testch"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["setup_complete"] is True
    assert data["next_url"] == "/index.html"
    assert (tmp_setup_root / ".setup_complete").exists()


def test_wizard_cannot_run_twice(client, tmp_setup_root):
    """Once .setup_complete exists, /complete returns 409 unless force."""
    (tmp_setup_root / ".setup_complete").write_text("done")
    r = client.post("/api/setup/complete", json={"church_id": "testch"})
    assert r.status_code == 409
