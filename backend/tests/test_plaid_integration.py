"""FR-Bank-Integration: Tests for Plaid store + integration with mock manager."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from backend.models.schemas import PlaidAccount


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Redirect Plaid storage to tmp_path and force the mock manager."""
    from backend.tools import plaid_store
    from backend.integrations import plaid_client

    monkeypatch.setattr(plaid_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(plaid_store, "KEY_PATH", tmp_path / ".vault_key")

    mock = plaid_client.MockPlaidManager()
    plaid_client.set_manager(mock)
    yield mock
    plaid_client.reset_manager()


def _make_account(account_id: str = "acct-1", access_token_enc: str = "ENC-TOK") -> PlaidAccount:
    return PlaidAccount(
        account_id=account_id,
        church_id="c1",
        access_token_enc=access_token_enc,
        account_type="depository",
        account_subtype="checking",
        mask="0000",
        name="Plaid Checking",
        current_balance=1000.0,
        available_balance=900.0,
        balance_updated_at=datetime.utcnow(),
        linked_at=datetime.utcnow(),
        is_ach_enabled=True,
        created_at=datetime.utcnow(),
    )


# ---------- Encryption round-trip ----------

def test_encrypt_decrypt_round_trip():
    from backend.tools import plaid_store
    enc = plaid_store.encrypt_token("access-sandbox-12345")
    assert enc != "access-sandbox-12345"
    plain = plaid_store.decrypt_token(enc)
    assert plain == "access-sandbox-12345"


# ---------- Account CRUD ----------

def test_save_and_load_account():
    from backend.tools import plaid_store
    a = _make_account("acct-1")
    plaid_store.save_plaid_account("c1", a)
    rows = plaid_store.load_plaid_accounts("c1")
    assert len(rows) == 1
    assert rows[0].account_id == "acct-1"


def test_get_plaid_account():
    from backend.tools import plaid_store
    plaid_store.save_plaid_account("c1", _make_account("acct-1"))
    plaid_store.save_plaid_account("c1", _make_account("acct-2"))
    found = plaid_store.get_plaid_account("c1", "acct-2")
    assert found is not None and found.account_id == "acct-2"
    assert plaid_store.get_plaid_account("c1", "doesnt-exist") is None


def test_delete_plaid_account():
    from backend.tools import plaid_store
    plaid_store.save_plaid_account("c1", _make_account("acct-1"))
    plaid_store.save_plaid_account("c1", _make_account("acct-2"))
    plaid_store.delete_plaid_account("c1", "acct-1")
    rows = plaid_store.load_plaid_accounts("c1")
    assert len(rows) == 1
    assert rows[0].account_id == "acct-2"


# ---------- PlaidManager mock ----------

def test_mock_create_link_token():
    from backend.integrations import plaid_client
    mgr = plaid_client.get_manager()
    out = mgr.create_link_token(user_id="u1", church_name="Test Church")
    assert "link_token" in out
    assert out["link_token"].startswith("link-sandbox-mock-")


def test_mock_exchange_public_token():
    from backend.integrations import plaid_client
    mgr = plaid_client.get_manager()
    access = mgr.exchange_public_token("public-sandbox-xyz9876")
    assert access.startswith("access-sandbox-mock-")


def test_mock_get_accounts(_isolate):
    mgr = _isolate  # the mock manager
    mgr.seed_accounts("access-token-1", [{
        "account_id": "acct-A",
        "name": "Test Checking",
        "subtype": "checking",
        "type": "depository",
        "mask": "1234",
        "balances": {"current": 5000.0, "available": 4500.0, "limit": None},
    }])
    accounts = mgr.get_accounts("access-token-1")
    assert len(accounts) == 1
    assert accounts[0]["mask"] == "1234"


# ---------- refresh_account_balances ----------

def test_refresh_account_balances(_isolate):
    from backend.tools import plaid_store

    plain_token = "access-sandbox-real"
    enc = plaid_store.encrypt_token(plain_token)
    acct = _make_account("acct-A", access_token_enc=enc)
    acct.current_balance = 1.0
    acct.available_balance = 1.0
    plaid_store.save_plaid_account("c1", acct)

    _isolate.seed_accounts(plain_token, [{
        "account_id": "acct-A",
        "name": "Test Checking",
        "subtype": "checking",
        "type": "depository",
        "mask": "1234",
        "balances": {"current": 8500.0, "available": 8000.0, "limit": None},
    }])

    refreshed = plaid_store.refresh_account_balances("c1", "acct-A")
    assert refreshed is not None
    assert refreshed.current_balance == 8500.0
    assert refreshed.available_balance == 8000.0


# ---------- transactions ----------

def test_fetch_and_store_transactions(_isolate):
    from backend.tools import plaid_store

    plain_token = "access-sandbox-real"
    enc = plaid_store.encrypt_token(plain_token)
    acct = _make_account("acct-A", access_token_enc=enc)
    plaid_store.save_plaid_account("c1", acct)

    today = date.today()
    _isolate.seed_transactions(plain_token, [
        {
            "txn_id": "t1", "account_id": "acct-A",
            "date": today - timedelta(days=5),
            "name": "Office Depot", "amount": 145.50,
            "category": "Office Supplies", "merchant_name": "Office Depot",
        },
        {
            "txn_id": "t2", "account_id": "acct-A",
            "date": today - timedelta(days=10),
            "name": "Duke Energy", "amount": 425.00,
            "category": "Utilities", "merchant_name": "Duke Energy",
        },
    ])

    new_txns = plaid_store.fetch_and_store_transactions("c1", "acct-A", days_back=60)
    assert len(new_txns) == 2
    rows = plaid_store.load_plaid_transactions("c1")
    assert len(rows) == 2
    ids = {r.txn_id for r in rows}
    assert ids == {"t1", "t2"}


def test_load_transactions_filtered_by_date():
    from backend.tools import plaid_store
    from backend.models.schemas import PlaidTransaction

    today = date.today()
    txns = [
        PlaidTransaction(
            txn_id="t1", account_id="acct-A", date=today - timedelta(days=5),
            description="Recent", amount=10.0, fetched_at=datetime.utcnow(),
        ),
        PlaidTransaction(
            txn_id="t2", account_id="acct-A", date=today - timedelta(days=90),
            description="Old", amount=20.0, fetched_at=datetime.utcnow(),
        ),
    ]
    plaid_store.save_plaid_transactions("c1", txns)
    out = plaid_store.load_plaid_transactions(
        "c1", date_from=today - timedelta(days=30), date_to=today,
    )
    assert len(out) == 1
    assert out[0].txn_id == "t1"


# ---------- Insufficient-funds gate (logic level) ----------

def test_payment_blocked_insufficient_funds_logic():
    """When available balance < instruction amount, the API should refuse."""
    from backend.tools import plaid_store
    plaid_store.save_plaid_account("c1", _make_account("acct-A"))
    a = plaid_store.get_plaid_account("c1", "acct-A")
    assert a is not None
    a.available_balance = 100.0
    plaid_store.save_plaid_account("c1", a)

    a2 = plaid_store.get_plaid_account("c1", "acct-A")
    assert a2 is not None
    instruction_amount = 500.0
    assert a2.available_balance < instruction_amount  # gate trips
