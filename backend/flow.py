"""EIME CrewAI Flow — orchestrates the full invoice processing pipeline.

Pipeline per FRS §3.3 + risk/fraud/denomination extensions:
  extract → load_coa → denomination_rules → classify → risk_assess → fraud_detect
  → map → review → (hitl?) → build_entry → emit
"""
from __future__ import annotations
import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from decimal import Decimal

from .models import (
    AccountingContext, BudgetStatus, ClassifiedLineItem, DocumentType, DraftAllocations,
    HITLDecisions, InvoiceDocument, JournalEntry, ProcessingJob, ProcessingStatus,
    ReviewedAllocations, ReviewedLine,
)
from .tools import coa_store
from .tools.pdf_extractor import extract_invoice
from .tools.classifier import classify_line_items
from .tools.denomination_rules import apply_denomination_rules
from .tools.gl_mapper import map_line_items
from .tools.reviewer import review_allocations
from .tools.journal_builder import build_journal_entry
from .tools.risk_assessor import assess_risk
from .tools.fraud_detector import assess_fraud
from .tools.budget_comparator import compare_to_budget
from .tools.approval_chain_resolver import find_chain_for_gl
from .tools.approval_audit import append_event as append_approval_event
from .integrations.email import tokens as email_tokens
from .integrations.email.smtp_sender import send_email

# In-memory job store (replace with Redis/DB for production)
_jobs: Dict[str, ProcessingJob] = {}


def get_job(job_id: str) -> Optional[ProcessingJob]:
    return _jobs.get(job_id)


def list_jobs(church_id: Optional[str] = None) -> List[ProcessingJob]:
    jobs = list(_jobs.values())
    if church_id:
        jobs = [j for j in jobs if j.church_id == church_id]
    return sorted(jobs, key=lambda j: j.created_at, reverse=True)


def _update_job(job: ProcessingJob, status: ProcessingStatus, **kwargs: Any) -> None:
    job.status = status
    job.updated_at = datetime.utcnow()
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.audit_log.append({
        "ts": datetime.utcnow().isoformat(),
        "status": status.value,
        "detail": kwargs.get("error_message") or str(status.value),
    })


def create_job(church_id: str, filename: str, pdf_path: str,
               document_type: DocumentType) -> ProcessingJob:
    now = datetime.utcnow()
    job = ProcessingJob(
        job_id=str(uuid.uuid4()),
        church_id=church_id,
        filename=filename,
        pdf_path=pdf_path,
        document_type=document_type,
        status=ProcessingStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )
    _jobs[job.job_id] = job
    return job


async def run_pipeline(job_id: str) -> None:
    """Async pipeline runner — extract → denomination → classify → risk → fraud → map → review → (hitl?) → build."""
    job = _jobs.get(job_id)
    if not job:
        return

    try:
        # Step 1: PDF extraction
        _update_job(job, ProcessingStatus.EXTRACTING)
        await asyncio.sleep(0)
        invoice: InvoiceDocument = await asyncio.get_event_loop().run_in_executor(
            None, extract_invoice, job.pdf_path, job.document_type
        )
        job.invoice_document = invoice
        job.audit_log.append({
            "ts": datetime.utcnow().isoformat(),
            "status": "EXTRACTING",
            "detail": f"Extracted {len(invoice.line_items)} line items from {job.filename}",
        })

        # Step 2: COA load
        ctx: Optional[AccountingContext] = await asyncio.get_event_loop().run_in_executor(
            None, coa_store.load_accounting_context, job.church_id
        )
        if ctx is None:
            _update_job(job, ProcessingStatus.ERROR,
                        error_message="COA not configured for this church.")
            return
        job.accounting_context = ctx

        # Step 3: Classification
        _update_job(job, ProcessingStatus.CLASSIFYING)
        await asyncio.sleep(0)
        classified: List[ClassifiedLineItem] = await asyncio.get_event_loop().run_in_executor(
            None, classify_line_items, invoice, ctx, []
        )

        # Step 3b: Apply denomination-specific overrides
        classified = await asyncio.get_event_loop().run_in_executor(
            None, apply_denomination_rules, classified, ctx
        )
        job.classified_items = classified
        job.audit_log.append({
            "ts": datetime.utcnow().isoformat(),
            "status": "CLASSIFYING",
            "detail": f"Classified {len(classified)} lines; denomination={ctx.denomination_type}",
        })

        # Step 4: Risk assessment
        draft_placeholder = await asyncio.get_event_loop().run_in_executor(
            None, map_line_items, invoice, classified, ctx, None
        )
        risk_result = await asyncio.get_event_loop().run_in_executor(
            None, assess_risk, classified, draft_placeholder, ctx, []
        )
        job.risk_assessment = risk_result.to_dict()
        job.audit_log.append({
            "ts": datetime.utcnow().isoformat(),
            "status": "CLASSIFYING",
            "detail": f"Risk assessment: {risk_result.risk_level} (score={risk_result.risk_score:.3f})",
        })

        # Step 5: Fraud assessment
        fraud_result = await asyncio.get_event_loop().run_in_executor(
            None, assess_fraud, invoice, classified, ctx, []
        )
        job.fraud_assessment = fraud_result.to_dict()
        job.audit_log.append({
            "ts": datetime.utcnow().isoformat(),
            "status": "CLASSIFYING",
            "detail": f"Fraud assessment: {fraud_result.fraud_level} (score={fraud_result.fraud_score:.3f}) — {fraud_result.recommended_action}",
        })

        # Escalate to HITL immediately if CRITICAL fraud
        if fraud_result.fraud_level == "CRITICAL":
            job.draft_allocations = draft_placeholder
            job.reviewed_allocations = None
            _update_job(job, ProcessingStatus.PENDING_HITL)
            job.audit_log.append({
                "ts": datetime.utcnow().isoformat(),
                "status": "PENDING_HITL",
                "detail": "CRITICAL fraud score — escalated to Finance Committee before GL mapping",
            })
            return

        # Step 6: GL mapping (use the already-computed draft)
        _update_job(job, ProcessingStatus.MAPPING)
        await asyncio.sleep(0)
        job.draft_allocations = draft_placeholder

        # Step 7: Allocation review
        _update_job(job, ProcessingStatus.REVIEWING)
        await asyncio.sleep(0)
        reviewed: ReviewedAllocations = await asyncio.get_event_loop().run_in_executor(
            None, review_allocations, job.draft_allocations, classified, ctx
        )
        job.reviewed_allocations = reviewed

        # Merge risk CRITICAL lines into escalation
        if job.risk_assessment:
            critical_lines = [
                lr["line_id"] for lr in job.risk_assessment.get("per_line_risks", [])
                if lr["risk_level"] == "CRITICAL"
            ]
            for lid in critical_lines:
                if lid not in reviewed.escalation_items:
                    reviewed.escalation_items.append(lid)
                    reviewed.review_notes += f" [Risk CRITICAL: {lid}]"

        # Step 7b: Budget check (only if a budget plan is configured)
        if ctx.budget is not None and job.draft_allocations is not None:
            budget_results = await asyncio.get_event_loop().run_in_executor(
                None, compare_to_budget, job.draft_allocations, ctx
            )
            job.budget_check = budget_results

            over = [b for b in budget_results if b.status == BudgetStatus.OVER_BUDGET]
            warn = [b for b in budget_results if b.status == BudgetStatus.WARNING]

            # Inject reasons into existing reviewed.lines (so HITL modal sees them)
            by_line: Dict[str, ReviewedLine] = {l.line_id: l for l in reviewed.lines}
            for b in budget_results:
                if b.status in (BudgetStatus.OVER_BUDGET, BudgetStatus.WARNING):
                    rl = by_line.get(b.line_id)
                    if rl is not None:
                        rl.reasons.append(b.reason)

            # Escalate OVER lines (WARNING is informational only)
            for b in over:
                if b.line_id not in reviewed.escalation_items:
                    reviewed.escalation_items.append(b.line_id)

            job.audit_log.append({
                "ts": datetime.utcnow().isoformat(),
                "step": "budget_check",
                "status": "REVIEWING",
                "detail": (
                    f"Budget check: {len(over)} OVER, {len(warn)} WARNING, "
                    f"{len(budget_results)} lines checked"
                ),
                "over": len(over),
                "warning": len(warn),
                "total_lines_checked": len(budget_results),
            })

        # Step 7c: FR-05.2 budget-owner approval gate.
        if await _maybe_request_budget_owner_approval(job, reviewed):
            return

        # Step 8: HITL gate
        if reviewed.escalation_items:
            _update_job(job, ProcessingStatus.PENDING_HITL)
            return

        # Steps 9–10: Journal entry
        await _build_and_emit(job, reviewed, None)

    except Exception as exc:
        _update_job(job, ProcessingStatus.ERROR, error_message=str(exc))
        raise


async def _maybe_request_budget_owner_approval(
    job: ProcessingJob,
    reviewed: ReviewedAllocations,
) -> bool:
    """FR-05.2: scan draft allocations, find a configured approval chain.

    If a chain matches, mint approval tokens, email the budget owner, set the
    job to PENDING_BUDGET_OWNER, and return True. Otherwise return False.
    """
    if not job.draft_allocations or not job.invoice_document:
        return False

    chain = None
    matched_line = None
    matched_gl = None
    for ln in job.draft_allocations.lines:
        for p in ln.postings:
            try:
                c = find_chain_for_gl(job.church_id, p.account_number)
            except Exception:
                c = None
            if c:
                chain = c
                matched_line = ln
                matched_gl = p
                break
        if chain:
            break
    if not chain or not matched_line or not matched_gl:
        return False

    base_ctx = {
        "job_id": job.job_id,
        "line_id": matched_line.line_id,
        "approver_email": chain.primary_approver_email,
        "proposed_gl_code": matched_gl.account_number,
    }
    deadline_h = max(1, int(chain.deadline_hours or 48))
    ttl = deadline_h * 3600
    approve_token = email_tokens.mint("APPROVE", base_ctx, "budget_owner", ttl)
    correct_token = email_tokens.mint("CORRECT", base_ctx, "budget_owner", ttl)
    reject_token = email_tokens.mint("REJECT", base_ctx, "budget_owner", ttl)

    base_url = os.environ.get("EIME_PUBLIC_URL", "http://localhost:8000")
    approve_url = f"{base_url}/api/approve?token={approve_token}&action=approve"
    correct_url = f"{base_url}/api/approve?token={correct_token}&action=correct"
    reject_url = f"{base_url}/api/approve?token={reject_token}&action=reject"

    annual_budget = "0"
    ytd_actual = "0"
    if job.budget_check:
        for bc in job.budget_check:
            if bc.line_id == matched_line.line_id:
                annual_budget = str(bc.annual_budget)
                ytd_actual = str(bc.ytd_actual)
                break

    invoice = job.invoice_document
    amount = matched_line.total_debits
    projected_after = Decimal(str(ytd_actual or "0")) + Decimal(str(amount or "0"))
    annual_dec = Decimal(str(annual_budget or "0"))
    pct = float(projected_after / annual_dec * 100) if annual_dec > 0 else 0.0

    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        tpl_dir = Path(__file__).resolve().parent / "integrations" / "email" / "templates"
        env = Environment(
            loader=FileSystemLoader(str(tpl_dir)),
            autoescape=select_autoescape(["html", "j2"]),
        )
        tpl = env.get_template("budget_owner.j2")
        html_body = tpl.render(
            vendor_name=invoice.vendor_name,
            amount=str(amount),
            approver_name=chain.primary_approver_name,
            invoice_date=str(invoice.invoice_date),
            proposed_gl_code=matched_gl.account_number,
            proposed_gl_name=matched_gl.account_name,
            annual_budget=annual_budget,
            ytd_actual=ytd_actual,
            projected_after=str(projected_after),
            projected_pct=f"{pct:.1f}",
            approve_url=approve_url,
            correct_url=correct_url,
            reject_url=reject_url,
        )
    except Exception as exc:
        html_body = (
            f"<p>Approval required for {invoice.vendor_name} — ${amount}.</p>"
            f"<p><a href='{approve_url}'>Approve</a> | "
            f"<a href='{correct_url}'>Correct</a> | "
            f"<a href='{reject_url}'>Reject</a></p>"
            f"<!-- template render failed: {exc} -->"
        )

    subject = f"Approval Request: {invoice.vendor_name} — ${amount}"
    try:
        send_email(chain.primary_approver_email, subject, html_body)
    except Exception:
        pass

    job.approval_chain_id = chain.chain_id
    job.pending_approval_email = chain.primary_approver_email
    job.pending_approval_started_at = datetime.utcnow()
    job.audit_log.append({
        "ts": datetime.utcnow().isoformat(),
        "event_type": "BUDGET_OWNER_REQUEST",
        "status": ProcessingStatus.PENDING_BUDGET_OWNER.value,
        "chain_id": chain.chain_id,
        "approver_email": chain.primary_approver_email,
        "matched_gl": matched_gl.account_number,
    })
    try:
        append_approval_event(job.church_id, {
            "job_id": job.job_id,
            "line_id": matched_line.line_id,
            "actor_email": "system@eime",
            "actor_role": "pipeline",
            "action": "REQUESTED_BUDGET_OWNER_APPROVAL",
            "gl_at_action": matched_gl.account_number,
            "notes": f"chain={chain.chain_id}",
        })
    except Exception:
        pass

    _update_job(job, ProcessingStatus.PENDING_BUDGET_OWNER)
    return True


async def continue_after_treasurer(job_id: str) -> None:
    """FR-05.3: resume `_build_and_emit` after treasurer approves."""
    job = _jobs.get(job_id)
    if not job:
        return
    if job.status != ProcessingStatus.TREASURER_APPROVED:
        return
    if job.reviewed_allocations is None:
        return
    await _build_and_emit(job, job.reviewed_allocations, job.hitl_decisions)


async def submit_hitl_decisions(job_id: str, decisions: HITLDecisions) -> None:
    """Resume the pipeline after HITL review gate."""
    job = _jobs.get(job_id)
    if not job or job.status != ProcessingStatus.PENDING_HITL:
        return
    job.hitl_decisions = decisions
    if job.reviewed_allocations:
        # FR-05: route through budget-owner gate before emitting.
        if await _maybe_request_budget_owner_approval(job, job.reviewed_allocations):
            return
        await _build_and_emit(job, job.reviewed_allocations, decisions)
    else:
        # Was escalated before review (CRITICAL fraud) — build review from scratch
        if job.draft_allocations and job.classified_items and job.accounting_context:
            reviewed = await asyncio.get_event_loop().run_in_executor(
                None, review_allocations,
                job.draft_allocations, job.classified_items, job.accounting_context
            )
            job.reviewed_allocations = reviewed
            if await _maybe_request_budget_owner_approval(job, reviewed):
                return
            await _build_and_emit(job, reviewed, decisions)


_FUND_RESTRICTION_MARKERS = (
    "RestrictionClass",
    "restricted",
    "WITH_RESTRICTION_PERMANENT",
    "WITH_RESTRICTION_PURPOSE",
    "fund restriction",
    "Fund restriction",
)


def _has_fund_restriction_violation(reviewed: ReviewedAllocations) -> bool:
    """FR-04.3: detect any ESCALATE line carrying a fund-restriction reason."""
    from .models import Verdict
    for rl in reviewed.lines:
        if rl.verdict != Verdict.ESCALATE:
            continue
        for r in rl.reasons:
            if any(marker in r for marker in _FUND_RESTRICTION_MARKERS):
                return True
    return False


async def _build_and_emit(
    job: ProcessingJob,
    reviewed: ReviewedAllocations,
    hitl_decisions: Optional[HITLDecisions],
) -> None:
    # FR-04.3 hard block.
    if _has_fund_restriction_violation(reviewed):
        from .models import Verdict
        violating: List[str] = []
        for rl in reviewed.lines:
            if rl.verdict == Verdict.ESCALATE and any(
                m in r for r in rl.reasons for m in _FUND_RESTRICTION_MARKERS
            ):
                violating.append(rl.line_id)
        _update_job(job, ProcessingStatus.BLOCKED_FUND_RESTRICTION)
        job.audit_log.append({
            "ts": datetime.utcnow().isoformat(),
            "event_type": "FUND_RESTRICTION_BLOCK",
            "status": ProcessingStatus.BLOCKED_FUND_RESTRICTION.value,
            "violating_lines": violating,
            "detail": (
                f"Journal entry drafting refused: {len(violating)} line(s) "
                f"have fund-restriction violations."
            ),
        })
        return

    _update_job(job, ProcessingStatus.BUILDING_ENTRY)
    await asyncio.sleep(0)

    je: JournalEntry = await asyncio.get_event_loop().run_in_executor(
        None, build_journal_entry,
        job.invoice_document, job.draft_allocations, reviewed,
        job.accounting_context, hitl_decisions,
    )
    job.journal_entry = je

    _update_job(job, ProcessingStatus.EMITTED)
    job.audit_log.append({
        "ts": datetime.utcnow().isoformat(),
        "status": "EMITTED",
        "detail": (
            f"Journal entry {je.entry_id} ({je.status}) — "
            f"${je.total_debits} debits / ${je.total_credits} credits, balanced={je.balanced}"
        ),
    })

    # Post-EMIT: update YTD actuals if a budget is configured.
    # Critical invariant: only runs on EMITTED status (rejected/cancelled jobs do NOT touch YTD).
    ctx = job.accounting_context
    if (
        job.status == ProcessingStatus.EMITTED
        and ctx is not None
        and ctx.budget is not None
        and job.journal_entry is not None
    ):
        try:
            updates: Dict[str, Decimal] = {}
            for jl in job.journal_entry.lines:
                debit = Decimal(jl.debit or Decimal("0"))
                if debit > Decimal("0"):
                    current = ctx.ytd_actuals.get(jl.account_number, Decimal("0"))
                    new_total = Decimal(current) + debit
                    ctx.ytd_actuals[jl.account_number] = new_total
                    updates[jl.account_number] = new_total
            await asyncio.get_event_loop().run_in_executor(
                None, coa_store.save_accounting_context, ctx
            )
            job.audit_log.append({
                "ts": datetime.utcnow().isoformat(),
                "status": "EMITTED",
                "step": "ytd_update",
                "detail": f"YTD actuals updated for {len(updates)} account(s)",
                "updates": {k: str(v) for k, v in updates.items()},
            })
        except Exception as exc:
            # Don't fail the request — log it. Reconcile-on-restart is deferred.
            job.audit_log.append({
                "ts": datetime.utcnow().isoformat(),
                "status": "EMITTED",
                "step": "ytd_update_failed",
                "detail": f"YTD persistence failed: {exc}",
            })
