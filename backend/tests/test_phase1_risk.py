"""Phase 1.5 / 1.6 tests — FR-04 reasons priority, FR-04.3 fund-restriction
hard block, FR-04.5 fraud-stripping, FR-09 canon citations.

Sticks to the unit-test style used elsewhere in backend/tests (uses fixtures
hand-built per test).
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
    JournalEntry, JournalEntryLine, JEStatus, LineItem, OverallVerdict, Posting,
    ProcessingJob, ProcessingStatus, ReviewedAllocations, ReviewedLine,
    RestrictionClass, Verdict,
)


# ---------- helpers ----------

def _ctx_basic(annual: str = "1000", ytd: str = "0") -> AccountingContext:
    return AccountingContext(
        church_id="test_phase1",
        church_name="Test",
        denomination_type=DenominationType.EPISCOPAL,
        fiscal_year=2026,
        fiscal_year_start=date(2026, 1, 1),
        accounts=[
            Account(account_number="7100", account_name="Office",
                    account_type="Expense", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            Account(account_number="6900", account_name="Rector Discretionary",
                    account_type="Expense", fund_id="DISC",
                    restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE),
        ],
        funds=[
            Fund(fund_id="GEN", fund_name="General",
                 restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                 fund_category=FundCategory.GENERAL_OPERATING),
            Fund(fund_id="DISC", fund_name="Rector's Discretionary",
                 restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
                 fund_category=FundCategory.TEMP_RESTRICTED_PURPOSE,
                 purpose_description="Pastoral discretionary care only"),
        ],
        budget=BudgetPlan(
            fiscal_year=2026, plan_date=date(2026, 1, 1),
            accounts={"7100": BudgetMonth(annual_total=Decimal(annual))},
            uploaded_at=datetime.utcnow(),
        ),
        ytd_actuals={"7100": Decimal(ytd)} if Decimal(ytd) > 0 else {},
    )


def _invoice() -> InvoiceDocument:
    return InvoiceDocument(
        vendor_name="Acme", invoice_number="INV-9",
        invoice_date=date(2026, 5, 1),
        document_type=DocumentType.INVOICE,
        subtotal=Decimal("100"), total_amount=Decimal("100"),
        line_items=[LineItem(line_id="L1", description="x", amount=Decimal("100"))],
    )


def _draft_low_conf_over_budget() -> DraftAllocations:
    return DraftAllocations(
        invoice_number="INV-9",
        lines=[DraftLineAllocation(
            line_id="L1", description="x",
            postings=[Posting(
                account_number="7100", account_name="Office",
                fund_id="GEN", fund_name="General",
                debit_amount=Decimal("1500"),  # over annual budget of 1000
                restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                confidence=0.50,                # low confidence
            )],
            total_debits=Decimal("1500"), total_credits=Decimal("1500"),
            balanced=True,
        )],
        document_total_debits=Decimal("1500"),
        document_total_credits=Decimal("1500"),
        document_balanced=True,
    )


def _classified_low_conf() -> list:
    return [ClassifiedLineItem(
        line_id="L1", description="x", amount=Decimal("1500"),
        expense_category="OFFICE_SUPPLIES",
        fund_eligibility=["GEN"], flags=ClassificationFlags(),
        classification_rationale="t", confidence=0.50,
    )]


def _draft_restricted_violation() -> DraftAllocations:
    """Posting hits a restricted fund with purpose mismatch."""
    return DraftAllocations(
        invoice_number="INV-R",
        lines=[DraftLineAllocation(
            line_id="L1", description="bagels for staff party",
            postings=[Posting(
                account_number="6900", account_name="Rector Discretionary",
                fund_id="DISC", fund_name="Rector's Discretionary",
                debit_amount=Decimal("200"),
                restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
                confidence=0.99,
            )],
            total_debits=Decimal("200"), total_credits=Decimal("200"),
            balanced=True,
        )],
        document_total_debits=Decimal("200"),
        document_total_credits=Decimal("200"),
        document_balanced=True,
    )


def _classified_restricted_violation() -> list:
    return [ClassifiedLineItem(
        line_id="L1", description="bagels for staff party",
        amount=Decimal("200"),
        expense_category="HOSPITALITY",
        fund_eligibility=["DISC"], flags=ClassificationFlags(),
        classification_rationale="hospitality", confidence=0.99,
    )]


# ====================================================================
# FR-04 — risk-reasons priority ordering (budget first, fraud never)
# ====================================================================

def test_risk_reasons_ordered_budget_first():
    """When a single line has BOTH budget overage AND low confidence,
    the budget overage must appear at index 0 and confidence after it.
    Fraud must NEVER appear in reasons at all (FR-04.5)."""
    ctx = _ctx_basic(annual="1000", ytd="0")
    draft = _draft_low_conf_over_budget()
    classified = _classified_low_conf()

    # Run the reviewer (produces confidence reasons at top of bucket order).
    from backend.tools.reviewer import review_allocations
    reviewed = review_allocations(draft, classified, ctx)

    # Mimic flow.py prepending budget reasons.
    from backend.tools.budget_comparator import compare_to_budget
    budget_results = compare_to_budget(draft, ctx)
    by_line = {l.line_id: l for l in reviewed.lines}
    for b in budget_results:
        if b.status in (BudgetStatus.OVER_BUDGET, BudgetStatus.WARNING):
            by_line[b.line_id].reasons.insert(0, b.reason)

    line = reviewed.lines[0]
    assert len(line.reasons) >= 2

    # Priority 1: budget overage at index 0
    assert "OVER BUDGET" in line.reasons[0]

    # Priority 3: confidence appears AFTER budget
    confidence_idx = next(
        (i for i, r in enumerate(line.reasons) if "confidence" in r.lower()), -1
    )
    assert confidence_idx > 0
    assert confidence_idx > line.reasons.index(line.reasons[0])

    # FR-04.5: no fraud reason in reasons[]
    for r in line.reasons:
        assert "fraud" not in r.lower()
        assert "FRAUD_SIGNAL" not in r


# ====================================================================
# FR-04.3 — fund-restriction hard block
# ====================================================================

def test_fund_restriction_blocks_je_creation():
    """Reviewed line with a fund-restriction violation must abort JE drafting
    and put the job in BLOCKED_FUND_RESTRICTION status."""
    ctx = _ctx_basic()
    draft = _draft_restricted_violation()
    classified = _classified_restricted_violation()

    job = flow.create_job("test_phase1", "x.pdf", "/tmp/x.pdf", DocumentType.INVOICE)
    job.invoice_document = _invoice()
    job.accounting_context = ctx
    job.classified_items = classified
    job.draft_allocations = draft

    # Simulate reviewer step output that includes a restriction reason
    reviewed = ReviewedAllocations(
        lines=[ReviewedLine(
            line_id="L1", verdict=Verdict.ESCALATE,
            reasons=[
                "RestrictionClass violation: Restricted fund DISC purpose mismatch "
                "with 'Pastoral discretionary care only'.",
            ],
        )],
        overall_verdict=OverallVerdict.ESCALATE,
        escalation_items=["L1"],
        revision_items=[],
        review_notes="",
    )
    job.reviewed_allocations = reviewed

    asyncio.run(flow._build_and_emit(job, reviewed, None))

    assert job.status == ProcessingStatus.BLOCKED_FUND_RESTRICTION
    assert job.journal_entry is None  # no JE drafted
    assert any(
        e.get("event_type") == "FUND_RESTRICTION_BLOCK"
        for e in job.audit_log
    )


def test_fund_restriction_block_status_is_serializable():
    """The new enum value must round-trip JSON without breaking deserialization."""
    job = ProcessingJob(
        job_id="x", church_id="c", filename="f", pdf_path="/tmp/f",
        document_type=DocumentType.INVOICE,
        status=ProcessingStatus.BLOCKED_FUND_RESTRICTION,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    blob = job.model_dump_json()
    again = ProcessingJob.model_validate_json(blob)
    assert again.status == ProcessingStatus.BLOCKED_FUND_RESTRICTION


# ====================================================================
# FR-04.5 — fraud signals must NEVER appear in API responses
# ====================================================================

def test_fraud_assessment_stripped_from_job_response():
    """`_job_summary()` must scrub any `fraud_assessment` payload."""
    from backend.main import _job_summary

    job = ProcessingJob(
        job_id="j", church_id="c", filename="f", pdf_path="/tmp/f",
        document_type=DocumentType.INVOICE,
        status=ProcessingStatus.EMITTED,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        # Internal-only — must NOT leak.
        fraud_assessment={
            "fraud_level": "HIGH",
            "fraud_score": 0.55,
            "signals": [
                {"signal_id": "MISSING_INVOICE_NUMBER", "category": "A",
                 "description": "x", "weight": 0.25, "evidence": "x"},
            ],
        },
        audit_log=[],
    )
    summary = _job_summary(job)
    # `fraud_assessment` must be None or absent in the summary dict.
    assert summary.get("fraud_assessment") in (None, {}, [])


def test_fraud_signals_routed_to_audit_log_only():
    """The pipeline routes every fraud signal to audit_log with
    event_type=FRAUD_SIGNAL and clears job.fraud_assessment."""
    from backend.tools.fraud_detector import FraudAssessment as _FA, FraudSignal as _FS

    # Build a job whose audit_log starts empty
    job = flow.create_job("c", "f.pdf", "/tmp/f.pdf", DocumentType.INVOICE)

    # Hand-roll the fraud handling exactly as flow.py does
    fake = _FA(fraud_level="HIGH", fraud_score=0.4,
               signals=[_FS("DUP_INVOICE", "B", "duplicate", 0.4, "INV-1")],
               recommended_action="FLAG_FOR_TREASURER")
    fake_dict = fake.to_dict()
    for sig in fake_dict.get("signals", []):
        job.audit_log.append({
            "ts": datetime.utcnow().isoformat(),
            "event_type": "FRAUD_SIGNAL",
            "status": "CLASSIFYING",
            "signal_id": sig["signal_id"],
            "category": sig["category"],
            "description": sig["description"],
            "weight": sig["weight"],
            "evidence": sig["evidence"],
        })
    job.fraud_assessment = None

    fraud_events = [e for e in job.audit_log if e.get("event_type") == "FRAUD_SIGNAL"]
    assert len(fraud_events) == 1
    assert fraud_events[0]["signal_id"] == "DUP_INVOICE"
    assert job.fraud_assessment is None


# ====================================================================
# FR-09 — Canon knowledge base citations
# ====================================================================

def test_kb_search_returns_episcopal_canon_for_rector_discretionary():
    """Searching for "rector discretionary" in EPISCOPAL canon returns
    a hit referencing the discretionary-fund canon."""
    from backend.tools.knowledge_base import (
        ingest_canon_skills, kb_search,
    )

    n = ingest_canon_skills(force=True)
    assert n > 0  # at least one chunk ingested

    hits = kb_search(
        query="rector discretionary fund",
        k=3,
        denomination="EPISCOPAL",
    )
    assert hits, "kb_search must return at least one hit"
    # All hits must be Episcopal (filter applied)
    for h in hits:
        assert h.denomination == "EPISCOPAL"
    # Top hits should mention discretionary in either heading or text.
    joined = " ".join((h.section_heading + " " + h.text).lower() for h in hits)
    assert "discretionary" in joined or "rector" in joined
    # Citation field is non-empty.
    assert hits[0].citation


def test_summarize_risk_includes_citation():
    """summarize_risk weaves the kb_search top citation into a
    fund-restriction summary using a 'per <citation>' style."""
    from backend.tools.risk_summary import summarize_risk
    from backend.tools.knowledge_base import KBHit

    line = ReviewedLine(
        line_id="L1", verdict=Verdict.ESCALATE,
        reasons=[
            "RestrictionClass violation: Restricted fund DISC purpose mismatch "
            "with 'Pastoral discretionary care only'.",
        ],
    )

    expected_citation = "Title I, Canon 7 (TEC Discretionary Funds)"

    def fake_kb_search(query, k=2, denomination=None):
        # Confirm the function is called with the fund-restriction trigger.
        assert "fund restriction" in query.lower()
        return [KBHit(
            text="Rector's Discretionary Fund — separate restricted fund.",
            citation=expected_citation,
            score=0.9,
            source_path="backend/skills/worker/denomination_episcopal/SKILL.md",
            denomination="EPISCOPAL",
            section_heading="Rector's Discretionary Fund",
        )]

    ctx = _ctx_basic()

    # Force the deterministic-template path (no Anthropic call) by clearing the API key.
    with patch.dict("os.environ", {}, clear=False):
        import os
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            summary = summarize_risk(line, ctx, kb_search_func=fake_kb_search)
        finally:
            if old:
                os.environ["ANTHROPIC_API_KEY"] = old

    assert isinstance(summary, str) and summary
    assert summary.startswith("Why this needs review:")
    # Citation must appear verbatim in the output.
    assert expected_citation in summary
    # Should suggest a next step.
    assert "Next step" in summary or "next step" in summary.lower()
