"""Schema tests for budget models."""
from __future__ import annotations
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from backend.models import (
    AccountingContext, BudgetCheck, BudgetMonth, BudgetPlan, BudgetStatus,
)


def test_budget_month_defaults():
    bm = BudgetMonth()
    assert bm.jan == Decimal("0")
    assert bm.dec == Decimal("0")
    assert bm.annual_total == Decimal("0")


def test_budget_plan_round_trip():
    bp = BudgetPlan(
        fiscal_year=2026,
        plan_date=date(2026, 1, 15),
        amendment_number=0,
        accounts={"7100": BudgetMonth(annual_total=Decimal("24000"))},
        uploaded_at=datetime(2026, 1, 15, 12, 0, 0),
    )
    blob = bp.model_dump_json()
    parsed = json.loads(blob)
    assert parsed["fiscal_year"] == 2026
    assert "7100" in parsed["accounts"]
    bp2 = BudgetPlan.model_validate_json(blob)
    assert bp2.accounts["7100"].annual_total == Decimal("24000")


def test_budget_check_status_enum():
    bc = BudgetCheck(
        line_id="L1", account_number="7100", account_name="Office",
        fund_id="GEN", annual_budget=Decimal("100"), ytd_actual=Decimal("0"),
        this_invoice=Decimal("50"), after=Decimal("50"), remaining=Decimal("50"),
        consumed_pct=0.5, status=BudgetStatus.WITHIN_BUDGET, reason="ok",
    )
    assert bc.status == BudgetStatus.WITHIN_BUDGET


def test_existing_context_loads_without_budget():
    """Backward compat: existing JSON without budget field must still load."""
    p = Path(__file__).resolve().parent.parent / "data" / "context_holy_comforter.json"
    if not p.exists():
        pytest.skip("Holy Comforter context not present")
    raw = json.loads(p.read_text())
    ctx = AccountingContext.model_validate(raw)
    assert ctx.budget is None
    assert ctx.ytd_actuals == {}
    assert ctx.budget_warning_threshold == 0.80


def test_accounting_context_with_budget_round_trip():
    bp = BudgetPlan(
        fiscal_year=2026, plan_date=date(2026, 1, 1),
        accounts={"7100": BudgetMonth(annual_total=Decimal("24000"))},
        uploaded_at=datetime.utcnow(),
    )
    ctx_data = {
        "church_id": "test", "church_name": "Test",
        "denomination_type": "OTHER", "fiscal_year": 2026,
        "fiscal_year_start": "2026-01-01",
        "accounts": [], "funds": [],
        "budget": json.loads(bp.model_dump_json()),
        "ytd_actuals": {"7100": "100.00"},
        "budget_warning_threshold": 0.85,
    }
    ctx = AccountingContext.model_validate(ctx_data)
    assert ctx.budget is not None
    assert ctx.ytd_actuals["7100"] == Decimal("100.00")
    assert ctx.budget_warning_threshold == 0.85
