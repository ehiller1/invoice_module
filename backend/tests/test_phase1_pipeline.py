"""Phase 1 pipeline tests covering FR-01.5 (multi-page source tracking),
FR-02.3 (HITL override rationale), and FR-03.3 (year-forward projection).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Dict

import pytest

from backend.models.schemas import (
    Account,
    AccountingContext,
    BudgetMonth,
    BudgetPlan,
    DenominationType,
    Fund,
    FundCategory,
    LineItem,
    RestrictionClass,
)
from backend.tools.budget_projector import project_year_end


def _make_ctx_with_budget(
    annual_per_account: Dict[str, str],
    ytd_per_account: Dict[str, str],
    fiscal_year_start: date = date(2026, 1, 1),
    fiscal_year: int = 2026,
) -> AccountingContext:
    accounts = [
        Account(
            account_number=k,
            account_name=f"Account {k}",
            account_type="EXPENSE",
            fund_id="GEN",
            restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
            active=True,
        )
        for k in annual_per_account.keys()
    ]
    funds = [
        Fund(
            fund_id="GEN",
            fund_name="General",
            restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
            fund_category=FundCategory.GENERAL_OPERATING,
        )
    ]

    budget_accounts: Dict[str, BudgetMonth] = {}
    for k, annual in annual_per_account.items():
        monthly = Decimal(str(annual)) / Decimal("12")
        budget_accounts[k] = BudgetMonth(
            jan=monthly, feb=monthly, mar=monthly, apr=monthly, may=monthly, jun=monthly,
            jul=monthly, aug=monthly, sep=monthly, oct=monthly, nov=monthly, dec=monthly,
            annual_total=Decimal(str(annual)),
        )

    return AccountingContext(
        church_id="test",
        church_name="Test Church",
        denomination_type=DenominationType.EPISCOPAL,
        fiscal_year=fiscal_year,
        fiscal_year_start=fiscal_year_start,
        accounts=accounts,
        funds=funds,
        budget=BudgetPlan(
            fiscal_year=fiscal_year,
            plan_date=fiscal_year_start,
            amendment_number=0,
            accounts=budget_accounts,
            uploaded_at=datetime(fiscal_year_start.year, 1, 1),
            uploaded_by="tester",
            source_filename="test_budget.xlsx",
        ),
        ytd_actuals={k: Decimal(str(v)) for k, v in ytd_per_account.items()},
    )


# ===== FR-03.3 Year-forward projection =====

def test_projection_when_50pct_consumed_at_month_6_predicts_on_track():
    """At June 30 (6 months in), 50% of $12000 budget consumed →
    monthly_avg = 1000 → projected = $12000 → no overspend."""
    ctx = _make_ctx_with_budget(
        annual_per_account={"6500": "12000"},
        ytd_per_account={"6500": "6000"},
    )
    report = project_year_end(ctx, today=date(2026, 6, 30))
    assert len(report.accounts) == 1
    a = report.accounts[0]
    assert not a.will_overspend
    # 6000 / 6 * 12 = 12000 exactly
    assert a.projected_year_end == Decimal("12000.00")
    assert report.accounts_predicted_to_overspend == 0


def test_projection_when_75pct_consumed_at_month_6_predicts_overspend():
    """At June 30 (6 months in), 75% of $12000 budget consumed → projected = $18000 → overspend."""
    ctx = _make_ctx_with_budget(
        annual_per_account={"6500": "12000"},
        ytd_per_account={"6500": "9000"},
    )
    report = project_year_end(ctx, today=date(2026, 6, 30))
    assert len(report.accounts) == 1
    a = report.accounts[0]
    assert a.will_overspend
    assert a.projected_year_end > a.annual_budget
    # 9000 / 6 * 12 = 18000
    assert a.projected_year_end == Decimal("18000.00")
    assert a.projected_overage == Decimal("6000.00")
    assert report.accounts_predicted_to_overspend == 1
    assert report.total_projected_overage == Decimal("6000.00")


def test_projection_no_budget_returns_empty():
    """Church with no budget configured → empty projection."""
    accounts = [
        Account(
            account_number="6500",
            account_name="Maintenance",
            account_type="EXPENSE",
            fund_id="GEN",
            restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
            active=True,
        )
    ]
    funds = [
        Fund(
            fund_id="GEN",
            fund_name="General",
            restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
            fund_category=FundCategory.GENERAL_OPERATING,
        )
    ]
    ctx = AccountingContext(
        church_id="test",
        church_name="Test",
        denomination_type=DenominationType.EPISCOPAL,
        fiscal_year=2026,
        fiscal_year_start=date(2026, 1, 1),
        accounts=accounts,
        funds=funds,
        budget=None,
        ytd_actuals={},
    )
    report = project_year_end(ctx, today=date(2026, 6, 30))
    assert len(report.accounts) == 0
    assert report.accounts_predicted_to_overspend == 0


def test_projection_zero_budget_account_skipped():
    """Accounts with annual_total <= 0 are skipped."""
    ctx = _make_ctx_with_budget(
        annual_per_account={"6500": "0"},
        ytd_per_account={"6500": "100"},
    )
    report = project_year_end(ctx, today=date(2026, 6, 30))
    assert len(report.accounts) == 0


def test_projection_sorts_by_overage_descending():
    """Highest overage should appear first."""
    ctx = _make_ctx_with_budget(
        annual_per_account={"6100": "12000", "6200": "6000", "6300": "24000"},
        ytd_per_account={"6100": "9000", "6200": "1000", "6300": "20000"},
    )
    report = project_year_end(ctx, today=date(2026, 6, 30))
    overages = [a.projected_overage for a in report.accounts]
    assert overages == sorted(overages, reverse=True)


# ===== FR-01.5 Multi-page source tracking =====

def test_multipage_lineitem_tracks_source_page():
    """LineItem schema has source_page field (FR-01.5)."""
    li = LineItem(
        line_id="L001",
        description="Test line on page 2",
        quantity=Decimal("1"),
        unit_price=Decimal("100"),
        amount=Decimal("100"),
        source_page=2,
    )
    assert li.source_page == 2


def test_multipage_lineitem_default_source_page_is_one():
    """source_page defaults to 1 when not provided."""
    li = LineItem(
        line_id="L001",
        description="Test line",
        amount=Decimal("100"),
    )
    assert li.source_page == 1


# ===== FR-02.3 HITL override rationale =====

def test_hitlline_decision_has_override_rationale_field():
    """HITLLineDecision exposes override_rationale (FR-02.3)."""
    from backend.models.schemas import HITLLineDecision
    d = HITLLineDecision(
        line_id="L001",
        action="OVERRIDE",
        reviewer_id="rev",
        approval_timestamp=datetime.utcnow(),
        override_rationale="Reviewer felt 6500 better fit",
    )
    assert d.override_rationale == "Reviewer felt 6500 better fit"


def test_hitlline_decision_override_rationale_optional():
    """override_rationale is optional / None by default."""
    from backend.models.schemas import HITLLineDecision
    d = HITLLineDecision(
        line_id="L001",
        action="APPROVED",
        reviewer_id="rev",
        approval_timestamp=datetime.utcnow(),
    )
    assert d.override_rationale is None


# ===== FR-03.3 API endpoint =====

def test_budget_projection_endpoint_returns_404_when_no_church():
    """GET /api/churches/{id}/budget/projection → 404 when church missing."""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    resp = client.get("/api/churches/__nonexistent__/budget/projection")
    assert resp.status_code == 404
