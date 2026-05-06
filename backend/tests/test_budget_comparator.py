"""Tests for compare_to_budget — pure deterministic logic."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.models import (
    Account, AccountingContext, BudgetMonth, BudgetPlan, BudgetStatus,
    DenominationType, DraftAllocations, DraftLineAllocation, Fund, FundCategory,
    Posting, RestrictionClass,
)
from backend.tools.budget_comparator import compare_to_budget


def _ctx(annual: str = "24000", ytd: str = "0", threshold: float = 0.80,
         budgeted: bool = True):
    bp = BudgetPlan(
        fiscal_year=2026, plan_date=date(2026, 1, 1),
        accounts={"7100": BudgetMonth(annual_total=Decimal(annual))} if budgeted else {},
        uploaded_at=datetime.utcnow(),
    )
    return AccountingContext(
        church_id="t", church_name="T", denomination_type=DenominationType.OTHER,
        fiscal_year=2026, fiscal_year_start=date(2026, 1, 1),
        accounts=[Account(account_number="7100", account_name="Office",
                          account_type="Expense", fund_id="GEN",
                          restriction_class=RestrictionClass.WITHOUT_RESTRICTION)],
        funds=[Fund(fund_id="GEN", fund_name="General",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                    fund_category=FundCategory.GENERAL_OPERATING)],
        budget=bp,
        ytd_actuals={"7100": Decimal(ytd)} if Decimal(ytd) > 0 else {},
        budget_warning_threshold=threshold,
    )


def _draft(amount: str, account: str = "7100"):
    return DraftAllocations(
        invoice_number="INV",
        lines=[DraftLineAllocation(
            line_id="L1", description="d", postings=[
                Posting(account_number=account, account_name="Office",
                        fund_id="GEN", fund_name="General",
                        debit_amount=Decimal(amount),
                        restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            ],
            total_debits=Decimal(amount), total_credits=Decimal("0"),
            balanced=False,
        )],
        document_total_debits=Decimal(amount),
        document_total_credits=Decimal("0"),
        document_balanced=False,
    )


def test_within_budget():
    ctx = _ctx(annual="24000", ytd="1000")
    results = compare_to_budget(_draft("500"), ctx)
    assert len(results) == 1
    assert results[0].status == BudgetStatus.WITHIN_BUDGET


def test_warning_at_81pct():
    # ytd=18000 + invoice=1500 = 19500 / 24000 = 81.25%, > 80% threshold but < 100%
    ctx = _ctx(annual="24000", ytd="18000")
    results = compare_to_budget(_draft("1500"), ctx)
    assert results[0].status == BudgetStatus.WARNING


def test_warning_with_higher_threshold_remains_within():
    # 81.25% with threshold 0.85 → still WITHIN
    ctx = _ctx(annual="24000", ytd="18000", threshold=0.85)
    results = compare_to_budget(_draft("1500"), ctx)
    assert results[0].status == BudgetStatus.WITHIN_BUDGET


def test_over_by_exact_penny():
    ctx = _ctx(annual="100", ytd="99.99")
    results = compare_to_budget(_draft("0.02"), ctx)
    assert results[0].status == BudgetStatus.OVER_BUDGET


def test_annual_zero_with_positive_invoice_is_over():
    ctx = _ctx(annual="0")
    results = compare_to_budget(_draft("100"), ctx)
    assert results[0].status == BudgetStatus.OVER_BUDGET


def test_no_budget_for_account():
    ctx = _ctx(budgeted=False)
    results = compare_to_budget(_draft("100"), ctx)
    assert results[0].status == BudgetStatus.NO_BUDGET


def test_credit_only_postings_skipped():
    ctx = _ctx()
    draft = DraftAllocations(
        invoice_number="INV",
        lines=[DraftLineAllocation(
            line_id="L1", description="d",
            postings=[
                Posting(account_number="7100", account_name="O", fund_id="GEN",
                        fund_name="G", debit_amount=Decimal("0"),
                        credit_amount=Decimal("500"),
                        restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            ],
            total_debits=Decimal("0"), total_credits=Decimal("500"),
            balanced=False,
        )],
        document_total_debits=Decimal("0"),
        document_total_credits=Decimal("500"),
        document_balanced=False,
    )
    assert compare_to_budget(draft, ctx) == []


def test_multi_line_mixed_statuses():
    bp = BudgetPlan(
        fiscal_year=2026, plan_date=date(2026, 1, 1),
        accounts={
            "7100": BudgetMonth(annual_total=Decimal("1000")),
            "7200": BudgetMonth(annual_total=Decimal("1000")),
        },
        uploaded_at=datetime.utcnow(),
    )
    ctx = AccountingContext(
        church_id="t", church_name="T", denomination_type=DenominationType.OTHER,
        fiscal_year=2026, fiscal_year_start=date(2026, 1, 1),
        accounts=[],
        funds=[],
        budget=bp,
        ytd_actuals={"7100": Decimal("950"), "7200": Decimal("100")},
    )
    draft = DraftAllocations(
        invoice_number="INV",
        lines=[
            DraftLineAllocation(
                line_id="L1", description="over",
                postings=[Posting(account_number="7100", account_name="A",
                                  fund_id="GEN", fund_name="G",
                                  debit_amount=Decimal("100"),
                                  restriction_class=RestrictionClass.WITHOUT_RESTRICTION)],
                total_debits=Decimal("100"), total_credits=Decimal("0"),
                balanced=False,
            ),
            DraftLineAllocation(
                line_id="L2", description="within",
                postings=[Posting(account_number="7200", account_name="B",
                                  fund_id="GEN", fund_name="G",
                                  debit_amount=Decimal("100"),
                                  restriction_class=RestrictionClass.WITHOUT_RESTRICTION)],
                total_debits=Decimal("100"), total_credits=Decimal("0"),
                balanced=False,
            ),
        ],
        document_total_debits=Decimal("200"),
        document_total_credits=Decimal("0"),
        document_balanced=False,
    )
    results = compare_to_budget(draft, ctx)
    statuses = {r.line_id: r.status for r in results}
    assert statuses["L1"] == BudgetStatus.OVER_BUDGET
    assert statuses["L2"] == BudgetStatus.WITHIN_BUDGET


def test_no_budget_plan_returns_empty():
    ctx = _ctx()
    ctx.budget = None
    results = compare_to_budget(_draft("100"), ctx)
    assert results == []
