"""Phase 2.6-2.7 tests: JE state machine + ACS Realm posting."""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest

# Set mock mode for all tests in this module before any acs_actions import.
os.environ["EIME_ACS_MOCK"] = "1"

from backend.models.schemas import (
    JEStatus,
    JournalEntry,
    JournalEntryLine,
)
from backend.tools.je_state import JEStateError, can_transition, transition


def _make_je(status: JEStatus = JEStatus.DRAFT) -> JournalEntry:
    """Build a minimal balanced JE for state-machine + ACS-posting tests."""
    lines = [
        JournalEntryLine(
            sequence=1,
            account_number="6500",
            account_name="Maintenance",
            fund_id="GEN",
            fund_name="General",
            debit=Decimal("100"),
            credit=Decimal("0"),
            memo="test",
        ),
        JournalEntryLine(
            sequence=2,
            account_number="2010",
            account_name="AP",
            fund_id="GEN",
            fund_name="General",
            debit=Decimal("0"),
            credit=Decimal("100"),
            memo="test",
        ),
    ]
    return JournalEntry(
        entry_id="JE-TEST-001",
        church_id="test_church",
        fiscal_year=2026,
        accounting_period="2026-05",
        entry_date=date(2026, 5, 1),
        reference="REF-001",
        vendor_name="Test Vendor",
        description="Test JE",
        status=status,
        lines=lines,
        total_debits=Decimal("100"),
        total_credits=Decimal("100"),
        balanced=True,
    )


# ---------- JE state machine ----------

def test_je_state_transition_draft_to_open():
    je = _make_je(status=JEStatus.DRAFT)
    je = transition(je, JEStatus.OPEN, "FINANCE_STAFF", "u@test.com", "review")
    assert je.status == JEStatus.OPEN


def test_je_state_transition_invalid_skip():
    """Cannot skip from DRAFT directly to APPROVED."""
    je = _make_je(status=JEStatus.DRAFT)
    with pytest.raises(JEStateError):
        transition(je, JEStatus.APPROVED, "TREASURER_ADMIN", "u@test.com")


def test_je_state_transition_role_gate():
    """Finance Staff cannot approve — only TREASURER_ADMIN can."""
    je = _make_je(status=JEStatus.PENDING_TREASURER)
    with pytest.raises(JEStateError):
        transition(je, JEStatus.APPROVED, "FINANCE_STAFF", "u@test.com")
    transition(je, JEStatus.APPROVED, "TREASURER_ADMIN", "t@test.com")
    assert je.status == JEStatus.APPROVED


def test_can_transition_returns_correct_booleans():
    assert can_transition(JEStatus.DRAFT, JEStatus.OPEN, "FINANCE_STAFF") is True
    assert can_transition(JEStatus.DRAFT, JEStatus.APPROVED, "TREASURER_ADMIN") is False
    assert can_transition(JEStatus.PENDING_TREASURER, JEStatus.APPROVED, "BUDGET_OWNER") is False
    assert can_transition(JEStatus.APPROVED, JEStatus.POSTED, "TREASURER_ADMIN") is True


# ---------- ACS Realm posting (mock mode) ----------

def test_acs_post_mock_mode_succeeds():
    from backend.integrations.acs_realm.acs_actions import (
        _is_mock_mode,
        post_journal_entry,
    )

    je = _make_je(status=JEStatus.APPROVED)
    assert _is_mock_mode() is True

    result = post_journal_entry(je, "test_church")
    assert result.success is True
    assert result.mock is True
    assert result.acs_reference is not None
    assert result.acs_reference.startswith("MOCK-")


# ---------- ACS credentials vault ----------

def test_acs_credentials_store_and_retrieve_roundtrip(tmp_path, monkeypatch):
    """Encrypted credential vault round-trips."""
    from backend.integrations.acs_realm import credentials as creds_mod

    # Skip if cryptography isn't available — store/retrieve relies on Fernet.
    if not creds_mod.CRYPTO_AVAILABLE:
        pytest.skip("cryptography not installed")

    monkeypatch.setattr(
        creds_mod, "VAULT_PATH", tmp_path / "acs_credentials.enc"
    )
    monkeypatch.setattr(creds_mod, "KEY_PATH", tmp_path / ".vault_key")

    creds_mod.store("test_church", "alice", "secret", "https://example.com")
    creds = creds_mod.retrieve("test_church")
    assert creds is not None
    assert creds["username"] == "alice"
    assert creds["password"] == "secret"
    assert creds["base_url"] == "https://example.com"


def test_acs_credentials_returns_none_when_no_vault(tmp_path, monkeypatch):
    from backend.integrations.acs_realm import credentials as creds_mod

    monkeypatch.setattr(
        creds_mod, "VAULT_PATH", tmp_path / "missing_vault.enc"
    )
    monkeypatch.setattr(creds_mod, "KEY_PATH", tmp_path / ".missing_key")

    creds = creds_mod.retrieve("nonexistent_church_xyz")
    assert creds is None or creds.get("username") is None
