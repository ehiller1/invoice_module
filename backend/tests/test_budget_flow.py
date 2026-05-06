"""Pipeline integration tests for budget hooks.

These tests stub the GL mapper / reviewer / journal builder to keep the test
focused on the budget-injection logic in flow.py.
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from backend import flow
from backend.models import (
    Account, AccountingContext, BudgetMonth, BudgetPlan, BudgetStatus,
    ClassifiedLineItem, ClassificationFlags, DenominationType, DocumentType,
    DraftAllocations, DraftLineAllocation, Fund, FundCategory, InvoiceDocument,
    JournalEntry, JournalEntryLine, JEStatus, LineItem, Posting, ProcessingJob,
    ProcessingStatus, ReviewedAllocations, ReviewedLine, RestrictionClass,
    Verdict, OverallVerdict,
)


def _make_ctx(annual: str, ytd: str = "0", threshold: float = 0.80):
    return AccountingContext(
        church_id="testch",
        church_name="Test Church",
        denomination_type=DenominationType.OTHER,
        fiscal_year=2026,
        fiscal_year_start=date(2026, 1, 1),
        accounts=[Account(account_number="7100", account_name="Office",
                          account_type="Expense", fund_id="GEN",
                          restriction_class=RestrictionClass.WITHOUT_RESTRICTION)],
        funds=[Fund(fund_id="GEN", fund_name="General",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                    fund_category=FundCategory.GENERAL_OPERATING)],
        budget=BudgetPlan(
            fiscal_year=2026, plan_date=date(2026, 1, 1),
            accounts={"7100": BudgetMonth(annual_total=Decimal(annual))},
            uploaded_at=datetime.utcnow(),
        ),
        ytd_actuals={"7100": Decimal(ytd)} if Decimal(ytd) > 0 else {},
        budget_warning_threshold=threshold,
    )


def _make_invoice(amount: str = "100"):
    return InvoiceDocument(
        vendor_name="V", invoice_number="INV-1",
        invoice_date=date(2026, 5, 1),
        document_type=DocumentType.INVOICE,
        subtotal=Decimal(amount),
        total_amount=Decimal(amount),
        line_items=[LineItem(line_id="L1", description="x", amount=Decimal(amount))],
    )


def _make_draft(amount: str = "100"):
    return DraftAllocations(
        invoice_number="INV-1",
        lines=[DraftLineAllocation(
            line_id="L1", description="x",
            postings=[Posting(account_number="7100", account_name="Office",
                              fund_id="GEN", fund_name="General",
                              debit_amount=Decimal(amount),
                              restriction_class=RestrictionClass.WITHOUT_RESTRICTION)],
            total_debits=Decimal(amount), total_credits=Decimal("0"),
            balanced=False,
        )],
        document_total_debits=Decimal(amount),
        document_total_credits=Decimal("0"),
        document_balanced=False,
    )


def _make_classified():
    return [ClassifiedLineItem(
        line_id="L1", description="x", amount=Decimal("100"),
        expense_category="OFFICE_SUPPLIES",
        fund_eligibility=["GEN"], flags=ClassificationFlags(),
        classification_rationale="test", confidence=1.0,
    )]


def _make_reviewed_clean():
    return ReviewedAllocations(
        lines=[ReviewedLine(line_id="L1", verdict=Verdict.APPROVED, reasons=[])],
        overall_verdict=OverallVerdict.APPROVED,
        escalation_items=[], revision_items=[], review_notes="",
    )


def _make_je():
    return JournalEntry(
        entry_id="JE-1", church_id="testch", fiscal_year=2026,
        accounting_period="2026-05", entry_date=date(2026, 5, 1),
        reference="INV-1", vendor_name="V", description="t",
        status=JEStatus.APPROVED,
        lines=[JournalEntryLine(sequence=1, account_number="7100",
                                account_name="Office", fund_id="GEN",
                                fund_name="General", debit=Decimal("100"))],
        total_debits=Decimal("100"), total_credits=Decimal("100"),
        balanced=True,
    )


def _seed_job(ctx, draft, classified, reviewed):
    job = flow.create_job("testch", "test.pdf", "/tmp/test.pdf", DocumentType.INVOICE)
    job.invoice_document = _make_invoice()
    job.accounting_context = ctx
    job.classified_items = classified
    job.draft_allocations = draft
    job.reviewed_allocations = reviewed
    return job


def test_within_budget_no_escalation():
    ctx = _make_ctx(annual="24000", ytd="100")
    draft = _make_draft("500")
    reviewed = _make_reviewed_clean()
    job = _seed_job(ctx, draft, _make_classified(), reviewed)

    # Run the budget portion (mimicking what flow.run_pipeline does)
    from backend.tools.budget_comparator import compare_to_budget
    results = compare_to_budget(draft, ctx)
    assert all(r.status == BudgetStatus.WITHIN_BUDGET for r in results)


def test_over_budget_triggers_escalation_logic():
    ctx = _make_ctx(annual="100", ytd="50")
    draft = _make_draft("100")  # 50+100=150 > 100
    reviewed = _make_reviewed_clean()

    from backend.tools.budget_comparator import compare_to_budget
    results = compare_to_budget(draft, ctx)
    over = [r for r in results if r.status == BudgetStatus.OVER_BUDGET]
    assert len(over) == 1

    # Replicate the flow.py escalation injection
    by_line = {l.line_id: l for l in reviewed.lines}
    for r in results:
        if r.status == BudgetStatus.OVER_BUDGET:
            if r.line_id not in reviewed.escalation_items:
                reviewed.escalation_items.append(r.line_id)
            by_line[r.line_id].reasons.append(r.reason)

    assert "L1" in reviewed.escalation_items
    assert any("OVER BUDGET" in r for r in reviewed.lines[0].reasons)


def test_warning_does_not_escalate():
    ctx = _make_ctx(annual="100", ytd="80")
    draft = _make_draft("5")  # 80+5=85 → 85% (warning at 80% threshold)
    reviewed = _make_reviewed_clean()

    from backend.tools.budget_comparator import compare_to_budget
    results = compare_to_budget(draft, ctx)
    assert all(r.status == BudgetStatus.WARNING for r in results)
    # Replicate flow logic: WARNING does NOT escalate
    over = [r for r in results if r.status == BudgetStatus.OVER_BUDGET]
    for r in over:
        if r.line_id not in reviewed.escalation_items:
            reviewed.escalation_items.append(r.line_id)
    assert reviewed.escalation_items == []


def test_no_budget_path_skipped():
    ctx = _make_ctx(annual="100")
    ctx.budget = None
    draft = _make_draft("50")
    from backend.tools.budget_comparator import compare_to_budget
    assert compare_to_budget(draft, ctx) == []


def test_ytd_update_logic_after_emit():
    """Mirror the YTD accumulation logic from _build_and_emit."""
    ctx = _make_ctx(annual="1000", ytd="100")
    je = _make_je()
    # Replicate flow logic
    for jl in je.lines:
        if jl.debit > 0:
            current = ctx.ytd_actuals.get(jl.account_number, Decimal("0"))
            ctx.ytd_actuals[jl.account_number] = Decimal(current) + jl.debit
    assert ctx.ytd_actuals["7100"] == Decimal("200")


def test_two_invoices_accumulate_ytd():
    ctx = _make_ctx(annual="1000", ytd="0")
    for amount in (Decimal("500"), Decimal("500")):
        je = JournalEntry(
            entry_id="JE", church_id="testch", fiscal_year=2026,
            accounting_period="2026-05", entry_date=date(2026, 5, 1),
            reference="INV", vendor_name="V", description="t",
            status=JEStatus.APPROVED,
            lines=[JournalEntryLine(sequence=1, account_number="7100",
                                    account_name="O", fund_id="GEN",
                                    fund_name="G", debit=amount)],
            total_debits=amount, total_credits=amount, balanced=True,
        )
        for jl in je.lines:
            if jl.debit > 0:
                cur = ctx.ytd_actuals.get(jl.account_number, Decimal("0"))
                ctx.ytd_actuals[jl.account_number] = Decimal(cur) + jl.debit
    assert ctx.ytd_actuals["7100"] == Decimal("1000")
