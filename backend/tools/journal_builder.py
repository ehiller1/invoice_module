"""Journal entry builder - implements the journal_entry_builder skill workflow."""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import List, Optional
import uuid

from ..models import (
    AccountingContext, DraftAllocations, HITLDecisions, InvoiceDocument,
    JEStatus, JournalEntry, JournalEntryLine, ReviewedAllocations,
    OverallVerdict, Verdict,
)


def build_journal_entry(
    invoice: InvoiceDocument,
    draft: DraftAllocations,
    reviewed: ReviewedAllocations,
    ctx: AccountingContext,
    hitl_decisions: Optional[HITLDecisions] = None,
) -> JournalEntry:
    """Implements journal_entry_builder skill steps 1-8."""
    # Step 1: period lock (simplified — assume open)
    entry_date = invoice.invoice_date
    period = f"{entry_date.year}-{entry_date.month:02d}"
    warnings: List[str] = []
    if entry_date.year < ctx.fiscal_year:
        warnings.append(f"Invoice date is in locked period; posted to {period}.")

    # Step 2: merge reviewed + HITL decisions
    hitl_map: dict = {}
    if hitl_decisions:
        for dec in hitl_decisions.line_decisions:
            hitl_map[dec.line_id] = dec

    # Build a map of draft postings by line_id
    draft_map = {dl.line_id: dl for dl in draft.lines}
    reviewed_map = {rl.line_id: rl for rl in reviewed.lines}

    # Step 3: sequence debit lines first, then credits
    all_lines: List[JournalEntryLine] = []
    seq = 1
    rejected_count = 0

    # Collect debits and credits separately for ordering
    debit_lines: List[JournalEntryLine] = []
    credit_lines: List[JournalEntryLine] = []

    for line_id, draft_line in draft_map.items():
        reviewed_line = reviewed_map.get(line_id)
        hitl_dec = hitl_map.get(line_id)

        # REJECTed lines excluded (FR-04.7)
        if hitl_dec and hitl_dec.action == "REJECT":
            rejected_count += 1
            warnings.append(f"Line {line_id} rejected by reviewer: {hitl_dec.notes}")
            continue

        # HITL override postings take precedence
        postings = draft_line.postings
        approved_by: Optional[str] = None
        if hitl_dec and hitl_dec.action == "OVERRIDE" and hitl_dec.override_postings:
            postings = hitl_dec.override_postings
            approved_by = hitl_dec.reviewer_id

        # Step 4: apply fund sub-ledger coding (account_number + fund_id = fully qualified)
        for posting in sorted(postings, key=lambda p: p.account_number):
            if posting.debit_amount > 0:
                debit_lines.append(JournalEntryLine(
                    sequence=0,
                    account_number=posting.account_number,
                    account_name=posting.account_name,
                    fund_id=posting.fund_id,
                    fund_name=posting.fund_name,
                    debit=posting.debit_amount,
                    credit=Decimal("0"),
                    memo=draft_line.description[:100],
                    approved_by=approved_by,
                ))
            elif posting.credit_amount > 0:
                credit_lines.append(JournalEntryLine(
                    sequence=0,
                    account_number=posting.account_number,
                    account_name=posting.account_name,
                    fund_id=posting.fund_id,
                    fund_name=posting.fund_name,
                    debit=Decimal("0"),
                    credit=posting.credit_amount,
                    memo=draft_line.description[:100],
                    approved_by=approved_by,
                ))

    for line in debit_lines + credit_lines:
        line.sequence = seq
        seq += 1

    all_lines = debit_lines + credit_lines

    # Step 5: final balance check
    total_debits = sum((l.debit for l in all_lines), Decimal("0"))
    total_credits = sum((l.credit for l in all_lines), Decimal("0"))
    balanced = total_debits == total_credits

    # Step 7: status
    has_hitl = hitl_decisions is not None
    if not balanced:
        status = JEStatus.DRAFT
        warnings.append("CRITICAL: Journal entry does not balance — manual review required.")
    elif has_hitl:
        status = JEStatus.PENDING_APPROVAL
    elif reviewed.overall_verdict == OverallVerdict.APPROVED:
        status = JEStatus.PENDING_APPROVAL
    else:
        status = JEStatus.DRAFT

    entry_id = f"JE-{invoice.invoice_number[:12]}-{uuid.uuid4().hex[:6].upper()}"

    return JournalEntry(
        entry_id=entry_id,
        church_id=ctx.church_id,
        fiscal_year=ctx.fiscal_year,
        accounting_period=period,
        entry_date=entry_date,
        reference=invoice.invoice_number,
        vendor_name=invoice.vendor_name,
        description=f"AP Invoice {invoice.invoice_number} - {invoice.vendor_name}",
        status=status,
        lines=all_lines,
        total_debits=total_debits,
        total_credits=total_credits,
        balanced=balanced,
        audit_trail_url=f"/api/audit/{entry_id}",
    )
