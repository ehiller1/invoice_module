"""FR-NF-Authority: Tests for the budgetary-authority routing matrix."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.models.schemas import BudgetaryAuthority


# ---------- Fixtures ----------

@pytest.fixture(autouse=True)
def _isolate_data(monkeypatch, tmp_path):
    """Redirect authority storage into tmp_path so tests don't pollute the
    real data dir."""
    from backend.tools import budgetary_authority as ba
    monkeypatch.setattr(ba, "DATA_DIR", tmp_path)
    yield


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


# ---------- CRUD ----------

def test_authority_crud_round_trip():
    from backend.tools import budgetary_authority as ba
    a1 = _auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)
    ba.save_authorities("c1", [a1])
    rows = ba.load_authorities("c1")
    assert len(rows) == 1
    assert rows[0].authority_id == "a1"
    assert rows[0].max_amount == 5000.0
    assert rows[0].gl_pattern == "6000-6999"


def test_authority_add_and_remove():
    from backend.tools import budgetary_authority as ba
    a1 = _auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)
    a2 = _auth("a2", "TREASURER_ADMIN", "*", 100000.0, can_override_restrictions=True)
    ba.add_authority("c1", a1)
    ba.add_authority("c1", a2)
    assert len(ba.load_authorities("c1")) == 2

    ba.remove_authority("c1", "a1")
    rows = ba.load_authorities("c1")
    assert len(rows) == 1
    assert rows[0].authority_id == "a2"


def test_authority_load_missing_returns_empty():
    from backend.tools import budgetary_authority as ba
    assert ba.load_authorities("never_seen_church") == []


# ---------- get_authority_for_role_and_gl ----------

def test_budget_owner_can_approve_within_authority():
    """Budget owner can approve GL 6500 for $3000 when authorized 6000-6999 up to $5000."""
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)
    ba.save_authorities("c1", [a])
    auth, reason = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "6500", "GEN", 3000.0,
    )
    assert auth is not None
    assert auth.authority_id == "a1"
    assert reason == ""


def test_budget_owner_cannot_approve_clergy_comp():
    """Budget owner with 6000-6999 authority cannot approve GL 5000 (clergy)."""
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)
    ba.save_authorities("c1", [a])
    auth, reason = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "5000", "GEN", 1000.0,
    )
    assert auth is None
    assert "no matching" in reason.lower() or "gl" in reason.lower()


def test_amount_limit_blocks_payment():
    """Budget owner authorized up to $5K is denied at $15K."""
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)
    ba.save_authorities("c1", [a])
    auth, reason = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "6500", "GEN", 15000.0,
    )
    assert auth is None
    assert "amount" in reason.lower() or "exceeds" in reason.lower()


def test_fund_restriction_filter_applied():
    """If authority restricts to GEN/OUTREACH, MEM-FUND is rejected."""
    from backend.tools import budgetary_authority as ba
    a = _auth(
        "a1", "BUDGET_OWNER", "6000-6999", 5000.0,
        fund_restrictions=["GEN", "OUTREACH"],
    )
    ba.save_authorities("c1", [a])
    auth, reason = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "6500", "MEM-FUND", 1000.0,
    )
    assert auth is None
    assert "fund" in reason.lower()


def test_fund_restriction_empty_means_all_funds_allowed():
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)
    ba.save_authorities("c1", [a])
    auth, _ = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "6500", "ANY-FUND", 100.0,
    )
    assert auth is not None


def test_role_mismatch_returns_none():
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)
    ba.save_authorities("c1", [a])
    auth, reason = ba.get_authority_for_role_and_gl(
        "c1", "FINANCE_STAFF", "6500", "GEN", 100.0,
    )
    assert auth is None
    assert "role" in reason.lower() or "no" in reason.lower()


def test_wildcard_pattern_matches():
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "TREASURER_ADMIN", "*", 100000.0)
    ba.save_authorities("c1", [a])
    auth, _ = ba.get_authority_for_role_and_gl(
        "c1", "TREASURER_ADMIN", "8410", "GEN", 50000.0,
    )
    assert auth is not None


def test_exact_pattern_matches():
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6500", 5000.0)
    ba.save_authorities("c1", [a])
    auth, _ = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "6500", "GEN", 100.0,
    )
    assert auth is not None
    auth2, reason = ba.get_authority_for_role_and_gl(
        "c1", "BUDGET_OWNER", "6501", "GEN", 100.0,
    )
    assert auth2 is None


# ---------- can_override_restriction ----------

def test_treasurer_can_override_fund_restriction():
    from backend.tools import budgetary_authority as ba
    a = _auth(
        "a1", "TREASURER_ADMIN", "*", 100000.0,
        can_override_restrictions=True,
    )
    ba.save_authorities("c1", [a])
    assert ba.can_override_restriction("c1", "TREASURER_ADMIN", "6500") is True


def test_budget_owner_cannot_override_by_default():
    from backend.tools import budgetary_authority as ba
    a = _auth("a1", "BUDGET_OWNER", "6000-6999", 5000.0)
    ba.save_authorities("c1", [a])
    assert ba.can_override_restriction("c1", "BUDGET_OWNER", "6500") is False
