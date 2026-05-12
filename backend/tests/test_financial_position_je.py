"""Tests for financial-position JE roll-up.

Verifies the round-3 fix: dashboard fund balances should reflect
posted journal entries, not just seeded opening balances.
"""
from __future__ import annotations

import os
import uuid
import pytest

# Skip cleanly when Postgres isn't reachable.
try:
    from backend.db.connection import execute_query
    execute_query("SELECT 1", fetch_one=True)
    _DB_OK = True
except Exception:  # pragma: no cover
    _DB_OK = False

pytestmark = pytest.mark.skipif(not _DB_OK, reason="Postgres not reachable in this environment")

CHURCH = os.environ.get("EMBARK_DEFAULT_CHURCH", "holy_comforter")


def _church_pk() -> int:
    row = execute_query("SELECT id FROM churches WHERE church_id = %s", (CHURCH,), fetch_one=True)
    assert row is not None
    return int(row["id"])


def _post_je(church_pk: int, fund_id: str, credit: float, debit: float = 0.0, account: str = "1010") -> int:
    """Insert a POSTED journal entry with one line. Returns je.id."""
    entry_id = f"je-test-{uuid.uuid4().hex[:10]}"
    # journal_entries row
    execute_query(
        """
        INSERT INTO journal_entries
            (entry_id, church_id, status, entry_date, total_debits, total_credits, is_balanced, source)
        VALUES (%s, %s, 'POSTED', CURRENT_DATE, %s, %s, true, 'TEST')
        """,
        (entry_id, church_pk, debit, credit),
    )
    row = execute_query("SELECT id FROM journal_entries WHERE entry_id = %s", (entry_id,), fetch_one=True)
    assert row is not None
    je_id = int(row["id"])
    # journal_entry_lines row
    execute_query(
        """
        INSERT INTO journal_entry_lines
            (journal_entry_id, account_number, fund_id, debit, credit, line_no)
        VALUES (%s, %s, %s, %s, %s, 1)
        """,
        (je_id, account, fund_id, debit, credit),
    )
    return je_id


@pytest.fixture(autouse=True)
def _cleanup():
    """Remove test JEs after each test."""
    yield
    try:
        execute_query("DELETE FROM journal_entries WHERE entry_id LIKE 'je-test-%'")
    except Exception:
        pass


class TestFinancialPositionJE:
    def test_opening_balance_returned_when_no_jes(self):
        """With no test JEs posted, balances equal opening_balance."""
        from backend.routes.financial_position import compute_position
        snap = compute_position(CHURCH)
        assert snap is not None
        # Every fund's posted_je_count should be 0 for a clean baseline.
        for f in snap["funds"]:
            assert f["posted_je_count"] == 0
            assert f["je_net"] == 0.0
            assert f["current_balance"] == f["opening_balance"]
        assert snap["confidence"]["gl_rollup"] == "MEDIUM"

    def test_posted_credit_increases_fund_balance(self):
        """A POSTED credit on a fund line should add to that fund's current_balance."""
        from backend.routes.financial_position import compute_position

        before = compute_position(CHURCH)
        gen_before = next(f for f in before["funds"] if f["fund_id"] == "GEN")

        _post_je(_church_pk(), fund_id="GEN", credit=2500.00)

        after = compute_position(CHURCH)
        gen_after = next(f for f in after["funds"] if f["fund_id"] == "GEN")

        assert gen_after["posted_je_count"] == gen_before["posted_je_count"] + 1
        assert pytest.approx(gen_after["je_net"], abs=0.01) == gen_before["je_net"] + 2500.00
        assert pytest.approx(gen_after["current_balance"], abs=0.01) == gen_before["current_balance"] + 2500.00
        # GL roll-up confidence flips to HIGH once any JE rolls in.
        assert after["confidence"]["gl_rollup"] == "HIGH"

    def test_posted_debit_decreases_fund_balance(self):
        from backend.routes.financial_position import compute_position
        before = compute_position(CHURCH)
        gen_before = next(f for f in before["funds"] if f["fund_id"] == "GEN")

        _post_je(_church_pk(), fund_id="GEN", debit=500.00, credit=0.0)

        after = compute_position(CHURCH)
        gen_after = next(f for f in after["funds"] if f["fund_id"] == "GEN")

        assert pytest.approx(gen_after["je_net"], abs=0.01) == gen_before["je_net"] - 500.00
        assert pytest.approx(gen_after["current_balance"], abs=0.01) == gen_before["current_balance"] - 500.00

    def test_draft_je_is_ignored(self):
        """Only POSTED entries roll into balances; DRAFT/PENDING are excluded."""
        from backend.routes.financial_position import compute_position

        church_pk = _church_pk()
        before = compute_position(CHURCH)
        gen_before = next(f for f in before["funds"] if f["fund_id"] == "GEN")

        # Insert a DRAFT JE — should NOT show up in roll-up.
        entry_id = f"je-test-{uuid.uuid4().hex[:10]}"
        execute_query(
            """
            INSERT INTO journal_entries
                (entry_id, church_id, status, entry_date, total_debits, total_credits, is_balanced, source)
            VALUES (%s, %s, 'DRAFT', CURRENT_DATE, 0, 999, true, 'TEST')
            """,
            (entry_id, church_pk),
        )
        je_id = execute_query("SELECT id FROM journal_entries WHERE entry_id = %s", (entry_id,), fetch_one=True)["id"]
        execute_query(
            """
            INSERT INTO journal_entry_lines (journal_entry_id, account_number, fund_id, debit, credit, line_no)
            VALUES (%s, '1010', 'GEN', 0, 999, 1)
            """,
            (je_id,),
        )

        after = compute_position(CHURCH)
        gen_after = next(f for f in after["funds"] if f["fund_id"] == "GEN")

        assert gen_after["posted_je_count"] == gen_before["posted_je_count"]
        assert gen_after["current_balance"] == gen_before["current_balance"]

    def test_totals_reflect_je_net(self):
        """The aggregate totals should track the net of posted JEs."""
        from backend.routes.financial_position import compute_position

        before = compute_position(CHURCH)

        # Two posted JEs across two different funds.
        church_pk = _church_pk()
        _post_je(church_pk, fund_id="GEN", credit=1000.00)
        _post_je(church_pk, fund_id="OUTREACH", credit=500.00, debit=200.00)

        after = compute_position(CHURCH)

        delta_total   = after["totals"]["total_fund_balance"] - before["totals"]["total_fund_balance"]
        delta_je_net  = after["totals"]["posted_je_net"]      - before["totals"]["posted_je_net"]
        delta_je_n    = after["totals"]["posted_je_count"]    - before["totals"]["posted_je_count"]

        assert delta_je_n == 2
        # Net: +1000 (GEN credit) + (500 - 200) (OUTREACH) = +1300.
        assert pytest.approx(delta_je_net,  abs=0.01) == 1300.00
        assert pytest.approx(delta_total,   abs=0.01) == 1300.00

    def test_line_without_fund_id_is_skipped(self):
        """A JE line with NULL fund_id can't be attributed and is excluded."""
        from backend.routes.financial_position import compute_position

        church_pk = _church_pk()
        before = compute_position(CHURCH)

        # Direct insert with fund_id=NULL.
        entry_id = f"je-test-{uuid.uuid4().hex[:10]}"
        execute_query(
            "INSERT INTO journal_entries (entry_id, church_id, status, entry_date, total_credits, is_balanced, source) "
            "VALUES (%s, %s, 'POSTED', CURRENT_DATE, 999, true, 'TEST')",
            (entry_id, church_pk),
        )
        je_id = execute_query("SELECT id FROM journal_entries WHERE entry_id=%s", (entry_id,), fetch_one=True)["id"]
        execute_query(
            "INSERT INTO journal_entry_lines (journal_entry_id, account_number, fund_id, credit, line_no) "
            "VALUES (%s, '1010', NULL, 999, 1)",
            (je_id,),
        )

        after = compute_position(CHURCH)
        # Total should be unchanged — the orphan line doesn't roll into any fund.
        assert after["totals"]["total_fund_balance"] == before["totals"]["total_fund_balance"]
