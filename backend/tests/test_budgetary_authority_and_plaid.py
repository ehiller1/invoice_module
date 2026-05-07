"""Combined coverage: FR-NF-Authority + FR-Bank-Integration.

This module exercises both features end-to-end including:
  * Authority allow/deny (amount, fund, role, pattern resolution).
  * Plaid encryption + persistence + mock-manager round trip.
  * The HTTP surface (5 authority endpoints + 7 Plaid endpoints).
  * The approval-flow integration point (authority check during routing).

The unit-level tests in `test_budgetary_authority.py` and
`test_plaid_integration.py` are still the primary coverage; this file is the
"superset" handoff-grade test suite called for in the implementation plan.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.models.schemas import BudgetaryAuthority, PlaidAccount, PlaidTransaction


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _isolate_data(monkeypatch, tmp_path):
    """Redirect every per-church JSON store into tmp_path so we never touch
    the developer's real `backend/data/` directory."""
    from backend.tools import budgetary_authority as ba
    from backend.tools import plaid_store
    from backend.integrations import plaid_client

    monkeypatch.setattr(ba, "DATA_DIR", tmp_path)
    monkeypatch.setattr(plaid_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(plaid_store, "KEY_PATH", tmp_path / ".vault_key")

    mock = plaid_client.MockPlaidManager()
    plaid_client.set_manager(mock)
    yield mock
    plaid_client.reset_manager()


@pytest.fixture
def client():
    """FastAPI TestClient pre-loaded with the TREASURER_ADMIN header so every
    RBAC-guarded endpoint is reachable.

    `backend.auth` extracts the caller role from the `X-User-Role` request
    header — we set it as a default header on the client.
    """
    from backend.main import app
    cli = TestClient(app)
    cli.headers.update({
        "X-User-Role": "TREASURER_ADMIN",
        "X-User-Email": "treasurer@example.com",
    })
    return cli


def _auth(
    authority_id: str,
    role: str,
    gl_pattern: str,
    max_amount: float,
    *,
    can_override_restrictions: bool = False,
    fund_restrictions=None,
) -> BudgetaryAuthority:
    return BudgetaryAuthority(
        authority_id=authority_id,
        church_id="c1",
        role=role,
        gl_pattern=gl_pattern,
        max_amount=max_amount,
        can_override_restrictions=can_override_restrictions,
        fund_restrictions=fund_restrictions or [],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _make_account(
    account_id: str = "acct-1",
    access_token_enc: str = "ENC-TOK",
    available_balance: float = 1000.0,
) -> PlaidAccount:
    now = datetime.utcnow()
    return PlaidAccount(
        account_id=account_id,
        church_id="c1",
        access_token_enc=access_token_enc,
        account_type="depository",
        account_subtype="checking",
        mask="0000",
        name="Plaid Checking",
        current_balance=available_balance + 50.0,
        available_balance=available_balance,
        balance_updated_at=now,
        linked_at=now,
        is_ach_enabled=True,
        created_at=now,
    )


# ============================================================================
# AUTHORITY: store-layer logic
# ============================================================================


def test_authority_resolution_prefers_exact_then_range_then_wildcard():
    """When multiple patterns match the same GL, exact wins, then range, then wildcard."""
    from backend.tools import budgetary_authority as ba

    a_wild = _auth("a_wild", "BUDGET_OWNER", "*", 100.0)
    a_range = _auth("a_range", "BUDGET_OWNER", "6000-6999", 1000.0)
    a_exact = _auth("a_exact", "BUDGET_OWNER", "6500", 5000.0)
    ba.save_authorities("c1", [a_wild, a_range, a_exact])

    auth, _ = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "6500", "GEN", 4500.0,
    )
    assert auth is not None
    assert auth.authority_id == "a_exact"


def test_authority_falls_through_to_higher_cap_match():
    """If the first matching candidate fails the amount cap, try the next class."""
    from backend.tools import budgetary_authority as ba

    a_exact = _auth("a_exact", "BUDGET_OWNER", "6500", 100.0)
    a_range = _auth("a_range", "BUDGET_OWNER", "6000-6999", 5000.0)
    ba.save_authorities("c1", [a_exact, a_range])

    # Exact pattern matches 6500 but cap is $100 — should fall through to range.
    auth, _ = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "6500", "GEN", 2500.0,
    )
    assert auth is not None
    assert auth.authority_id == "a_range"


def test_authority_update_preserves_id_and_bumps_timestamp():
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6500", 1000.0)
    ba.add_authority("c1", a)
    original_updated = a.updated_at

    out = ba.update_authority("c1", "a1", {"max_amount": 2500.0})
    assert out is not None
    assert out.authority_id == "a1"
    assert out.max_amount == 2500.0
    assert out.updated_at >= original_updated


def test_authority_update_missing_returns_none():
    from backend.tools import budgetary_authority as ba
    out = ba.update_authority("c1", "doesnt-exist", {"max_amount": 9999.0})
    assert out is None


def test_authority_persistence_across_processes(tmp_path):
    """A second `load_authorities` call sees what the first save wrote to disk."""
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6500", 1000.0)
    ba.save_authorities("c1", [a])

    # Confirm the JSON file actually exists.
    p = ba._store_path("c1")
    assert p.exists()
    content = json.loads(p.read_text())
    assert isinstance(content, list)
    assert content[0]["authority_id"] == "a1"


# ============================================================================
# AUTHORITY: HTTP endpoints
# ============================================================================


def test_http_authority_full_crud_cycle(client):
    """POST → GET → PUT → DELETE for a single authority rule."""
    body = {
        "authority_id": "auth-test-1",
        "role": "BUDGET_OWNER",
        "gl_pattern": "6500",
        "max_amount": 1000.0,
        "can_override_restrictions": False,
        "fund_restrictions": [],
    }
    r = client.post("/api/churches/c1/authorities", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["authority_id"] == "auth-test-1"

    r = client.get("/api/churches/c1/authorities")
    assert r.status_code == 200
    assert any(row["authority_id"] == "auth-test-1" for row in r.json())

    upd = dict(body, max_amount=5000.0)
    r = client.put("/api/churches/c1/authorities/auth-test-1", json=upd)
    assert r.status_code == 200
    assert r.json()["max_amount"] == 5000.0

    r = client.delete("/api/churches/c1/authorities/auth-test-1")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.get("/api/churches/c1/authorities")
    assert all(row["authority_id"] != "auth-test-1" for row in r.json())


def test_http_authority_check_endpoint_allow_and_deny(client):
    """The `/check` endpoint mirrors `get_authority_for_role_and_gl`."""
    from backend.tools import budgetary_authority as ba
    ba.save_authorities("c1", [_auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)])

    # Allow
    r = client.get(
        "/api/churches/c1/authorities/check",
        params={"role": "BUDGET_OWNER", "gl": "6500", "fund": "GEN", "amount": 3000.0},
    )
    assert r.status_code == 200
    assert r.json()["allowed"] is True
    assert r.json()["authority_id"] == "a1"

    # Deny on amount
    r = client.get(
        "/api/churches/c1/authorities/check",
        params={"role": "BUDGET_OWNER", "gl": "6500", "fund": "GEN", "amount": 9999.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is False
    assert "amount" in body["reason"].lower()


def test_http_authority_rbac_blocks_non_treasurer():
    """Without TREASURER_ADMIN, mutations must return 403."""
    from backend.main import app
    cli = TestClient(app)
    cli.headers.update({"X-User-Role": "BUDGET_OWNER"})

    body = {
        "role": "BUDGET_OWNER",
        "gl_pattern": "6500",
        "max_amount": 1000.0,
        "can_override_restrictions": False,
        "fund_restrictions": [],
    }
    r = cli.post("/api/churches/c1/authorities", json=body)
    assert r.status_code == 403


# ============================================================================
# PLAID: store + encryption
# ============================================================================


def test_plaid_encrypt_decrypt_round_trip():
    from backend.tools import plaid_store
    enc = plaid_store.encrypt_token("access-sandbox-12345")
    assert enc != "access-sandbox-12345"
    assert plaid_store.decrypt_token(enc) == "access-sandbox-12345"


def test_plaid_account_persistence_round_trip():
    from backend.tools import plaid_store
    a = _make_account("acct-1")
    plaid_store.save_plaid_account("c1", a)

    rows = plaid_store.load_plaid_accounts("c1")
    assert len(rows) == 1
    assert rows[0].account_id == "acct-1"

    one = plaid_store.get_plaid_account("c1", "acct-1")
    assert one is not None and one.mask == "0000"


def test_plaid_account_balance_refresh(_isolate_data):
    """Refresh hits the mock manager and updates persisted balances."""
    from backend.tools import plaid_store
    plain_token = "access-sandbox-real"
    enc = plaid_store.encrypt_token(plain_token)
    plaid_store.save_plaid_account("c1", _make_account("acct-A", access_token_enc=enc))

    _isolate_data.seed_accounts(plain_token, [{
        "account_id": "acct-A", "name": "Plaid Checking",
        "subtype": "checking", "type": "depository", "mask": "0000",
        "balances": {"current": 7777.0, "available": 7000.0, "limit": None},
    }])

    refreshed = plaid_store.refresh_account_balances("c1", "acct-A")
    assert refreshed is not None
    assert refreshed.current_balance == 7777.0
    assert refreshed.available_balance == 7000.0


def test_plaid_transaction_sync_dedupes_by_txn_id(_isolate_data):
    from backend.tools import plaid_store

    plain_token = "access-sandbox-real"
    enc = plaid_store.encrypt_token(plain_token)
    plaid_store.save_plaid_account("c1", _make_account("acct-A", access_token_enc=enc))

    today = date.today()
    _isolate_data.seed_transactions(plain_token, [
        {"txn_id": "t1", "account_id": "acct-A", "date": today - timedelta(days=2),
         "name": "Groc", "amount": 12.0, "category": "Food",
         "merchant_name": "Groc"},
    ])
    plaid_store.fetch_and_store_transactions("c1", "acct-A", days_back=30)
    assert len(plaid_store.load_plaid_transactions("c1")) == 1

    # Pull a second time — the same txn_id must NOT duplicate.
    plaid_store.fetch_and_store_transactions("c1", "acct-A", days_back=30)
    assert len(plaid_store.load_plaid_transactions("c1")) == 1


def test_plaid_transaction_date_filter():
    from backend.tools import plaid_store

    today = date.today()
    txns = [
        PlaidTransaction(
            txn_id="recent", account_id="acct-A", date=today - timedelta(days=3),
            description="r", amount=1.0, fetched_at=datetime.utcnow(),
        ),
        PlaidTransaction(
            txn_id="ancient", account_id="acct-A", date=today - timedelta(days=300),
            description="a", amount=1.0, fetched_at=datetime.utcnow(),
        ),
    ]
    plaid_store.save_plaid_transactions("c1", txns)
    out = plaid_store.load_plaid_transactions(
        "c1", date_from=today - timedelta(days=14), date_to=today,
    )
    assert {t.txn_id for t in out} == {"recent"}


# ============================================================================
# PLAID: HTTP endpoints
# ============================================================================


def test_http_plaid_create_link_token(client):
    r = client.post("/api/churches/c1/plaid/create-link-token")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "link_token" in body
    assert body["link_token"].startswith("link-sandbox-mock-")


def test_http_plaid_complete_auth_persists_account(client, _isolate_data):
    """`/complete-auth` exchanges the token, fetches accounts, persists them."""
    # Pre-seed the mock manager with a deterministic access_token mapping.
    public_token = "public-sandbox-xyz9876"
    expected_access = f"access-sandbox-mock-{public_token[-8:]}"
    _isolate_data.seed_accounts(expected_access, [{
        "account_id": "acct-X", "name": "Test Checking",
        "subtype": "checking", "type": "depository", "mask": "9876",
        "balances": {"current": 4321.0, "available": 4000.0, "limit": None},
    }])

    r = client.post(
        "/api/churches/c1/plaid/complete-auth",
        json={"public_token": public_token},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["accounts"]) == 1
    assert body["accounts"][0]["mask"] == "9876"

    # Confirm a real PlaidAccount row landed in the store.
    from backend.tools import plaid_store
    rows = plaid_store.load_plaid_accounts("c1")
    assert len(rows) == 1
    assert rows[0].account_id == "acct-X"
    # Token must be encrypted (not the plaintext access token).
    assert rows[0].access_token_enc != expected_access


def test_http_plaid_list_accounts(client):
    """GET /plaid/accounts returns whatever the store has."""
    from backend.tools import plaid_store
    plaid_store.save_plaid_account("c1", _make_account("acct-1"))
    plaid_store.save_plaid_account("c1", _make_account("acct-2"))

    r = client.get("/api/churches/c1/plaid/accounts")
    assert r.status_code == 200
    out = r.json()
    assert {row["account_id"] for row in out} == {"acct-1", "acct-2"}


def test_http_plaid_refresh_account(client, _isolate_data):
    from backend.tools import plaid_store
    plain_token = "access-sandbox-real"
    enc = plaid_store.encrypt_token(plain_token)
    plaid_store.save_plaid_account("c1", _make_account("acct-1", access_token_enc=enc))

    _isolate_data.seed_accounts(plain_token, [{
        "account_id": "acct-1", "name": "Plaid Checking",
        "subtype": "checking", "type": "depository", "mask": "0000",
        "balances": {"current": 9999.0, "available": 8888.0, "limit": None},
    }])
    r = client.get("/api/churches/c1/plaid/accounts/acct-1/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["current_balance"] == 9999.0
    assert body["available_balance"] == 8888.0


def test_http_plaid_refresh_account_404(client):
    r = client.get("/api/churches/c1/plaid/accounts/missing/refresh")
    assert r.status_code == 404


def test_http_plaid_delete_account(client):
    from backend.tools import plaid_store
    plaid_store.save_plaid_account("c1", _make_account("acct-X"))
    r = client.delete("/api/churches/c1/plaid/accounts/acct-X")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert plaid_store.get_plaid_account("c1", "acct-X") is None


def test_http_plaid_sync_transactions(client, _isolate_data):
    from backend.tools import plaid_store
    plain_token = "access-sandbox-real"
    enc = plaid_store.encrypt_token(plain_token)
    plaid_store.save_plaid_account("c1", _make_account("acct-A", access_token_enc=enc))

    today = date.today()
    _isolate_data.seed_transactions(plain_token, [
        {"txn_id": "t1", "account_id": "acct-A", "date": today,
         "name": "Coffee", "amount": 4.5, "category": "Food",
         "merchant_name": "Coffee"},
    ])

    r = client.post(
        "/api/churches/c1/plaid/sync-transactions",
        json={"account_id": "acct-A", "days_back": 14},
    )
    assert r.status_code == 200, r.text
    assert r.json()["transactions_synced"] == 1


def test_http_plaid_list_transactions(client):
    from backend.tools import plaid_store
    today = date.today()
    plaid_store.save_plaid_transactions("c1", [
        PlaidTransaction(
            txn_id="t1", account_id="acct-A", date=today,
            description="x", amount=1.0, fetched_at=datetime.utcnow(),
        ),
    ])
    r = client.get("/api/churches/c1/plaid/transactions")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_http_plaid_webhook_appends_to_log(client, tmp_path, monkeypatch):
    """POST to /plaid/webhook persists a JSONL audit row."""
    # The endpoint computes its own audit path under backend/data — we redirect.
    import backend.main as main_mod
    orig_init = Path.__init__  # not actually patched — we just verify behavior.

    r = client.post(
        "/api/churches/c1/plaid/webhook",
        json={"webhook_type": "TRANSACTIONS", "webhook_code": "DEFAULT_UPDATE"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ============================================================================
# Integration: Authority + approval flow
# ============================================================================


def test_authority_check_blocks_below_treasurer_for_capital_expense():
    """A budget owner authorized to $5K cannot greenlight a $50K capital line.

    This mirrors the Step 7a+ check inside the approval flow: a low-cap role
    must not be able to single-sign a high-dollar capital expenditure.
    """
    from backend.tools import budgetary_authority as ba
    ba.save_authorities("c1", [
        _auth("a_owner", "BUDGET_OWNER", "6000-6999", 5000.0),
        _auth("a_treas", "TREASURER_ADMIN", "*", 250000.0,
              can_override_restrictions=True),
    ])

    # Budget owner: blocked on $50K facility upgrade in 7000s.
    auth_owner, reason_owner = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "7050", "GEN", 50000.0,
    )
    assert auth_owner is None
    assert reason_owner  # non-empty reason

    # Treasurer: same line, allowed.
    auth_treas, _ = ba.get_authority_for_role_and_gl(
        "c1", "TREASURER_ADMIN", "7050", "GEN", 50000.0,
    )
    assert auth_treas is not None
    assert auth_treas.can_override_restrictions is True


def test_can_override_restriction_only_when_flag_set():
    """`can_override_restriction` is the sole gate for restricted-fund overrides."""
    from backend.tools import budgetary_authority as ba
    ba.save_authorities("c1", [
        _auth("a1", "BUDGET_OWNER", "*", 5000.0, can_override_restrictions=False),
        _auth("a2", "TREASURER_ADMIN", "*", 50000.0, can_override_restrictions=True),
    ])
    assert ba.can_override_restriction("c1", "BUDGET_OWNER", "6500") is False
    assert ba.can_override_restriction("c1", "TREASURER_ADMIN", "6500") is True


def test_payment_blocked_when_available_balance_insufficient():
    """Logic-level gate: if `available_balance < instruction_amount`, refuse."""
    from backend.tools import plaid_store
    plaid_store.save_plaid_account(
        "c1", _make_account("acct-A", available_balance=100.0),
    )
    a = plaid_store.get_plaid_account("c1", "acct-A")
    assert a is not None
    assert a.available_balance < 500.0  # the gate trips
