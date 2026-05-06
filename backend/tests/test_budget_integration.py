"""End-to-end pipeline integration tests for budget feature.

Drives backend.flow.run_pipeline with stubbed PDF extraction and stubbed
LLM-side tools so we can deterministically exercise the budget injection
path inside flow.run_pipeline without external dependencies.
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional
from unittest.mock import patch

import pytest

from backend import flow
from backend.models import (
    Account, AccountingContext, BudgetMonth, BudgetPlan, BudgetStatus,
    ClassifiedLineItem, ClassificationFlags, DenominationType, DocumentType,
    DraftAllocations, DraftLineAllocation, Fund, FundCategory,
    InvoiceDocument, JournalEntry, JournalEntryLine, JEStatus, LineItem,
    OverallVerdict, Posting, ProcessingStatus, RestrictionClass, ReviewedAllocations,
    ReviewedLine, Verdict,
)


# Lightweight stubs that mimic the dataclass-style RiskAssessment / FraudAssessment
# returned by backend.tools.risk_assessor.assess_risk and friends. They expose
# `.to_dict()`, the attributes flow.py reads, and use plain Python values.
class _RiskStub:
    def __init__(self) -> None:
        self.risk_level = "LOW"
        self.risk_score = 0.1
        self.per_line_risks: list = []
    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "per_line_risks": self.per_line_risks,
        }


class _FraudStub:
    def __init__(self) -> None:
        self.fraud_level = "LOW"
        self.fraud_score = 0.1
        self.recommended_action = "APPROVE"
    def to_dict(self) -> dict:
        return {
            "fraud_level": self.fraud_level,
            "fraud_score": self.fraud_score,
            "recommended_action": self.recommended_action,
        }


# --------- Helpers ---------

def _ctx(annual: str = "1000", ytd: str = "0", threshold: float = 0.80,
         budgeted: bool = True) -> AccountingContext:
    bp = None
    if budgeted:
        bp = BudgetPlan(
            fiscal_year=2026, plan_date=date(2026, 1, 1),
            accounts={"7100": BudgetMonth(annual_total=Decimal(annual))},
            uploaded_at=datetime.utcnow(),
        )
    return AccountingContext(
        church_id="ich",
        church_name="Integration Church",
        denomination_type=DenominationType.OTHER,
        fiscal_year=2026,
        fiscal_year_start=date(2026, 1, 1),
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


def _invoice(amount: str = "100") -> InvoiceDocument:
    return InvoiceDocument(
        vendor_name="Vendor", invoice_number="INV-1",
        invoice_date=date(2026, 5, 1),
        document_type=DocumentType.INVOICE,
        subtotal=Decimal(amount),
        total_amount=Decimal(amount),
        line_items=[LineItem(line_id="L1", description="Item", amount=Decimal(amount))],
    )


def _classified() -> List[ClassifiedLineItem]:
    return [ClassifiedLineItem(
        line_id="L1", description="Item", amount=Decimal("100"),
        expense_category="OFFICE_SUPPLIES",
        fund_eligibility=["GEN"], flags=ClassificationFlags(),
        classification_rationale="t", confidence=1.0,
    )]


def _draft(amount: str = "100") -> DraftAllocations:
    return DraftAllocations(
        invoice_number="INV-1",
        lines=[DraftLineAllocation(
            line_id="L1", description="Item",
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


def _reviewed_clean() -> ReviewedAllocations:
    return ReviewedAllocations(
        lines=[ReviewedLine(line_id="L1", verdict=Verdict.APPROVED, reasons=[])],
        overall_verdict=OverallVerdict.APPROVED,
        escalation_items=[], revision_items=[], review_notes="",
    )


def _journal_entry() -> JournalEntry:
    return JournalEntry(
        entry_id="JE-1", church_id="ich", fiscal_year=2026,
        accounting_period="2026-05", entry_date=date(2026, 5, 1),
        reference="INV-1", vendor_name="Vendor", description="t",
        status=JEStatus.APPROVED,
        lines=[JournalEntryLine(sequence=1, account_number="7100",
                                account_name="Office", fund_id="GEN",
                                fund_name="General", debit=Decimal("100"))],
        total_debits=Decimal("100"), total_credits=Decimal("100"),
        balanced=True,
    )


@pytest.fixture
def stub_pipeline_tools(monkeypatch):
    """Patch every tool used by flow.run_pipeline so we can drive it deterministically."""
    monkeypatch.setattr(flow, "extract_invoice", lambda path, dt: _invoice("100"))
    monkeypatch.setattr(flow, "classify_line_items",
                        lambda inv, ctx, _skills: _classified())
    monkeypatch.setattr(flow, "apply_denomination_rules",
                        lambda classified, ctx: classified)
    monkeypatch.setattr(flow, "map_line_items",
                        lambda inv, classified, ctx, _ext: _draft("100"))
    monkeypatch.setattr(flow, "assess_risk",
                        lambda *args, **kwargs: _RiskStub())
    monkeypatch.setattr(flow, "assess_fraud",
                        lambda *args, **kwargs: _FraudStub())
    monkeypatch.setattr(flow, "review_allocations",
                        lambda draft, classified, ctx: _reviewed_clean())
    monkeypatch.setattr(flow, "build_journal_entry",
                        lambda inv, draft, reviewed, ctx, hitl: _journal_entry())


@pytest.fixture
def isolated_jobs(monkeypatch):
    """Use a fresh in-memory job store per test."""
    monkeypatch.setattr(flow, "_jobs", {})


@pytest.fixture
def tmp_data_root(tmp_path, monkeypatch):
    from backend.tools import coa_store
    new_root = tmp_path / "data"
    new_root.mkdir()
    new_chroma = new_root / "chroma"
    new_chroma.mkdir()
    monkeypatch.setattr(coa_store, "DATA_ROOT", new_root)
    monkeypatch.setattr(coa_store, "CHROMA_DIR", new_chroma)
    monkeypatch.setattr(coa_store, "_chroma_client", None)
    monkeypatch.setattr(coa_store, "_rebuild_index", lambda ctx: None)
    yield new_root


def _seed_ctx(ctx: AccountingContext) -> None:
    from backend.tools import coa_store
    coa_store.save_accounting_context(ctx)


# --------- Tests ---------

def test_pipeline_within_budget_emits_je(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    """Within-budget invoice flows all the way through to EMITTED."""
    _seed_ctx(_ctx(annual="10000", ytd="0"))
    job = flow.create_job("ich", "test.pdf", "/tmp/test.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job.job_id))

    j = flow.get_job(job.job_id)
    assert j is not None
    assert j.status == ProcessingStatus.EMITTED, f"audit={j.audit_log}"
    # Budget check ran
    assert j.budget_check is not None
    assert all(b.status == BudgetStatus.WITHIN_BUDGET for b in j.budget_check)
    # YTD updated post-emit
    from backend.tools import coa_store
    persisted = coa_store.load_accounting_context("ich")
    assert persisted is not None
    assert persisted.ytd_actuals.get("7100") == Decimal("100")


def test_pipeline_over_budget_pauses_at_hitl(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    """Over-budget invoice escalates to PENDING_HITL."""
    _seed_ctx(_ctx(annual="50", ytd="0"))  # invoice 100 > annual 50
    job = flow.create_job("ich", "test.pdf", "/tmp/test.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job.job_id))

    j = flow.get_job(job.job_id)
    assert j is not None
    assert j.status == ProcessingStatus.PENDING_HITL
    over = [b for b in (j.budget_check or []) if b.status == BudgetStatus.OVER_BUDGET]
    assert len(over) == 1
    # Reason injected into reviewed line
    assert any("OVER BUDGET" in r for r in j.reviewed_allocations.lines[0].reasons)
    # Escalation item set
    assert "L1" in j.reviewed_allocations.escalation_items


def test_pipeline_warning_does_not_pause(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    """Warning-level invoice still emits a JE but logs the warning."""
    # ytd 80 + invoice 100 = 180 / 200 = 90% (warning threshold 80)
    _seed_ctx(_ctx(annual="200", ytd="80"))
    job = flow.create_job("ich", "test.pdf", "/tmp/test.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job.job_id))

    j = flow.get_job(job.job_id)
    assert j is not None
    assert j.status == ProcessingStatus.EMITTED
    warn = [b for b in (j.budget_check or []) if b.status == BudgetStatus.WARNING]
    assert len(warn) == 1


def test_pipeline_no_budget_skips_check(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    """No budget configured → budget_check is None, pipeline still emits."""
    _seed_ctx(_ctx(budgeted=False))
    job = flow.create_job("ich", "test.pdf", "/tmp/test.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job.job_id))

    j = flow.get_job(job.job_id)
    assert j is not None
    assert j.status == ProcessingStatus.EMITTED
    assert j.budget_check is None  # never set when ctx.budget is None


def test_pipeline_two_invoices_accumulate_ytd(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    """Successive EMITTED journal entries accumulate YTD and propagate to ctx."""
    _seed_ctx(_ctx(annual="1000", ytd="0"))
    job1 = flow.create_job("ich", "i1.pdf", "/tmp/i1.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job1.job_id))

    job2 = flow.create_job("ich", "i2.pdf", "/tmp/i2.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job2.job_id))

    from backend.tools import coa_store
    persisted = coa_store.load_accounting_context("ich")
    assert persisted is not None
    assert persisted.ytd_actuals.get("7100") == Decimal("200")


def test_pipeline_hitl_resolution_then_emit(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    """After OVER_BUDGET escalation, HITL APPROVE moves job to EMITTED + updates YTD."""
    from backend.models import HITLDecisions, HITLLineDecision
    from backend.tools import coa_store

    _seed_ctx(_ctx(annual="50", ytd="0"))  # over
    job = flow.create_job("ich", "i.pdf", "/tmp/i.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job.job_id))
    j = flow.get_job(job.job_id)
    assert j is not None
    assert j.status == ProcessingStatus.PENDING_HITL

    decisions = HITLDecisions(
        line_decisions=[HITLLineDecision(
            line_id="L1", action="APPROVED",
            reviewer_id="reviewer-1",
            approval_timestamp=datetime.utcnow(),
            notes="Authorized over-budget", missions_attestation=False,
        )],
        all_resolved=True,
    )
    asyncio.run(flow.submit_hitl_decisions(job.job_id, decisions))

    j2 = flow.get_job(job.job_id)
    assert j2 is not None
    assert j2.status == ProcessingStatus.EMITTED
    # YTD should be updated even after HITL approval
    persisted = coa_store.load_accounting_context("ich")
    assert persisted is not None
    assert persisted.ytd_actuals.get("7100") == Decimal("100")


def test_pipeline_audit_log_records_budget_check(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    _seed_ctx(_ctx(annual="10000", ytd="0"))
    job = flow.create_job("ich", "i.pdf", "/tmp/i.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job.job_id))

    j = flow.get_job(job.job_id)
    budget_audit = [
        e for e in (j.audit_log if j else []) if e.get("step") == "budget_check"
    ]
    assert len(budget_audit) == 1
    assert budget_audit[0]["over"] == 0


def test_pipeline_audit_log_records_ytd_update(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    _seed_ctx(_ctx(annual="10000", ytd="0"))
    job = flow.create_job("ich", "i.pdf", "/tmp/i.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job.job_id))

    j = flow.get_job(job.job_id)
    ytd_audit = [
        e for e in (j.audit_log if j else []) if e.get("step") == "ytd_update"
    ]
    assert len(ytd_audit) == 1


def test_pipeline_no_coa_returns_error(
    stub_pipeline_tools, isolated_jobs, tmp_data_root
):
    """Missing church context surfaces ERROR status (not budget-related, sanity check)."""
    job = flow.create_job("missing", "i.pdf", "/tmp/i.pdf", DocumentType.INVOICE)
    asyncio.run(flow.run_pipeline(job.job_id))
    j = flow.get_job(job.job_id)
    assert j is not None
    assert j.status == ProcessingStatus.ERROR
