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
from .decision_ledger import DecisionLedger, DecisionCategory, DecisionOutcome, LedgerEntry
from .db import processing_job_store, decision_ledger_store
from .events.emitter import emit_event
from .events.schemas import EventType, FinancialEvent, TagKind


def get_ledger(church_id: str) -> DecisionLedger:
    """Return the decision ledger for a church (loaded from DB)."""
    entries = decision_ledger_store.get_ledger(church_id)
    return DecisionLedger(church_id=church_id, entries=entries)


def _ledger_append(church_id: str, entry: LedgerEntry) -> None:
    """Append an entry to the church's decision ledger (fire-and-forget safe)."""
    try:
        decision_ledger_store.append_entry(church_id, entry)
    except Exception:
        pass  # ledger must never crash the pipeline


def get_job(job_id: str) -> Optional[ProcessingJob]:
    """Load a processing job from the database."""
    return processing_job_store.get_job(job_id)


def list_jobs(church_id: Optional[str] = None) -> List[ProcessingJob]:
    """List processing jobs (DB-backed). `church_id` is required."""
    if not church_id:
        raise ValueError("church_id required for list_jobs")
    return processing_job_store.list_jobs(church_id)


def _persist_job(job: ProcessingJob) -> None:
    """Write the full job state back to the database (upsert).

    The pipeline mutates `job` heavily in place. Calling this after each
    state transition keeps the DB row in sync with local state.
    """
    try:
        processing_job_store.create_job(job.church_id, job)
    except Exception:
        # Persistence must not crash the pipeline — surface via logs only.
        pass


def _update_job(job: ProcessingJob, status: ProcessingStatus, **kwargs: Any) -> None:
    """Update a job's status (and arbitrary fields) and persist to DB."""
    job.status = status
    job.updated_at = datetime.utcnow()
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.audit_log.append({
        "ts": datetime.utcnow().isoformat(),
        "status": status.value,
        "detail": kwargs.get("error_message") or str(status.value),
    })
    _persist_job(job)


def create_job(church_id: str, filename: str, pdf_path: str,
               document_type: DocumentType) -> ProcessingJob:
    """Create a new processing job and persist it."""
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
    processing_job_store.create_job(church_id, job)
    return job


async def run_pipeline(job_id: str) -> None:
    """Async pipeline runner — extract → denomination → classify → risk → fraud → map → review → (hitl?) → build."""
    job = processing_job_store.get_job(job_id)
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

        # Decision ledger — extraction confidence (RECOGNIZE membrane)
        _ledger_append(job.church_id, LedgerEntry(
            entry_id=str(uuid.uuid4()),
            decision_id=f"{job.job_id}:extraction",
            category=DecisionCategory.RECOGNIZE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_type": "pipeline", "actor_id": "pdf_extractor", "authority_tier": 0},
            policy_invoked="pdf_extraction_skill",
            evidence_refs=[job.job_id],
            inference_chain=[
                {"input": job.filename, "rule": "pdfplumber → pypdf → pytesseract OCR", "output": f"{len(invoice.line_items)} line items extracted"},
                {"input": f"warnings={invoice.warnings}", "rule": "requires_manual_review if ≥3 required fields missing", "output": f"requires_manual_review={invoice.requires_manual_review}"},
            ],
            conclusion=(
                f"Extracted {len(invoice.line_items)} line item(s) from {invoice.document_type} "
                f"for vendor '{invoice.vendor_name}', total ${invoice.total_amount}. "
                f"Warnings: {invoice.warnings or 'none'}."
            ),
            alternatives=[
                {"description": "Manual data entry", "rejection_rationale": "Auto-extraction attempted first; manual review flagged if confidence low"},
            ],
            outcome=DecisionOutcome.ACCEPTED if not invoice.requires_manual_review else DecisionOutcome.ESCALATED,
            metadata={"line_items": len(invoice.line_items), "total_amount": str(invoice.total_amount), "warnings": invoice.warnings},
        ))
        _persist_job(job)

        # Phase 5d: INSUFFICIENT_CONTEXT escalation. The vision says routing
        # should fire on genuine ambiguity, and zero line items is the
        # paradigm case. The Holy Comforter sample invoice produced 0 line
        # items (OCR fallback unconfigured) and the auto-reviewer rubber-
        # stamped it as APPROVED. That path is now closed: no line items,
        # or a vendor we couldn't read, sends the job straight to HITL with
        # an explicit reason — never auto-approve.
        _insufficient: List[str] = []
        if len(invoice.line_items) == 0:
            _insufficient.append("zero line items extracted")
        if not (invoice.vendor_name or "").strip() or invoice.vendor_name == "Unknown vendor":
            _insufficient.append("vendor name unreadable")
        if Decimal(str(invoice.total_amount or 0)) <= Decimal("0"):
            _insufficient.append("total amount zero or missing")
        if _insufficient:
            _update_job(job, ProcessingStatus.PENDING_HITL)
            job.audit_log.append({
                "ts": datetime.utcnow().isoformat(),
                "event_type": "INSUFFICIENT_CONTEXT",
                "status": ProcessingStatus.PENDING_HITL.value,
                "detail": (
                    f"Routed to HITL — insufficient context to auto-process: "
                    f"{', '.join(_insufficient)}. "
                    f"OCR warnings: {invoice.warnings or 'none'}."
                ),
                "reasons": _insufficient,
            })
            _ledger_append(job.church_id, LedgerEntry(
                entry_id=str(uuid.uuid4()),
                decision_id=f"{job.job_id}:insufficient_context",
                category=DecisionCategory.ROUTE,
                timestamp=datetime.utcnow(),
                authoring_actor={"actor_type": "pipeline", "actor_id": "context_evaluator", "authority_tier": 0},
                policy_invoked="insufficient_context_guard",
                evidence_refs=[job.job_id],
                inference_chain=[
                    {"input": f"line_items={len(invoice.line_items)}, vendor={invoice.vendor_name!r}, total=${invoice.total_amount}",
                     "rule": "auto-approve forbidden when context is insufficient",
                     "output": f"escalate: {', '.join(_insufficient)}"},
                ],
                conclusion=(
                    f"Insufficient context to auto-route: {', '.join(_insufficient)}. "
                    f"Job parked at PENDING_HITL for human review."
                ),
                alternatives=[
                    {"description": "Auto-approve with empty/low-confidence input",
                     "rejection_rationale": "Phase 5d guard: rote auto-approve on insufficient context is forbidden"},
                ],
                outcome=DecisionOutcome.ESCALATED,
                metadata={"reasons": _insufficient},
            ))
            return

        # Step 2: COA load
        ctx: Optional[AccountingContext] = await asyncio.get_event_loop().run_in_executor(
            None, coa_store.load_accounting_context, job.church_id
        )
        if ctx is None:
            _update_job(job, ProcessingStatus.ERROR,
                        error_message="COA not configured for this church.")
            return
        job.accounting_context = ctx

        # Phase 5d: emit a ContextAssembled event the moment the agent has
        # the full bundle it needs to decide. This is the canonical "agents
        # hold full context" record — every downstream DecisionRecorded
        # event in this job cites this context_event_id.
        context_event_id: Optional[str] = None
        try:
            ce = FinancialEvent(
                event_type=EventType.CONTEXT_ASSEMBLED,
                church_id=job.church_id,
                payload={
                    "job_id": job.job_id,
                    "vendor_name": invoice.vendor_name,
                    "invoice_number": invoice.invoice_number,
                    "total_amount": str(invoice.total_amount),
                    "line_items": len(invoice.line_items),
                    "denomination": str(getattr(ctx, "denomination_type", "")),
                    "fiscal_year": ctx.fiscal_year,
                    "fund_count": len(getattr(ctx, "funds", []) or []),
                    "budget_configured": ctx.budget is not None,
                    "ocr_warnings": invoice.warnings or [],
                },
                correlation_id=job.job_id,
            )
            ce.add_tag(TagKind.JOB, job.job_id)
            ce.add_tag(TagKind.VENDOR, invoice.vendor_name or "")
            ce.add_tag(TagKind.DENOMINATION, str(getattr(ctx, "denomination_type", "")))
            context_event_id = str(emit_event(ce))
        except Exception:
            context_event_id = None

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
        _persist_job(job)

        # Decision ledger — fraud assessment (ROUTE membrane)
        fraud_outcome = (
            DecisionOutcome.ESCALATED if fraud_result.fraud_level == "CRITICAL"
            else DecisionOutcome.ACCEPTED
        )
        _ledger_append(job.church_id, LedgerEntry(
            entry_id=str(uuid.uuid4()),
            decision_id=f"{job.job_id}:fraud",
            category=DecisionCategory.ROUTE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_type": "pipeline", "actor_id": "fraud_detector", "authority_tier": 0},
            policy_invoked="fraud_detection_skill",
            evidence_refs=[job.job_id],
            cited_event_ids=[context_event_id] if context_event_id else [],
            inference_chain=[
                {"input": f"vendor={getattr(invoice, 'vendor_name', '?')}, total=${getattr(invoice, 'total_amount', 0)}", "rule": "multi-signal fraud scoring", "output": f"score={fraud_result.fraud_score:.3f}"},
                {"input": f"score={fraud_result.fraud_score:.3f}", "rule": "CRITICAL if score ≥ threshold", "output": f"level={fraud_result.fraud_level}"},
            ],
            conclusion=(
                f"Fraud level: {fraud_result.fraud_level} (score={fraud_result.fraud_score:.3f}). "
                f"Recommended action: {fraud_result.recommended_action}."
            ),
            alternatives=[
                {"description": "Continue pipeline without fraud check", "rejection_rationale": "Policy requires fraud screening on all invoices"},
            ],
            outcome=fraud_outcome,
            metadata={"fraud_level": fraud_result.fraud_level, "fraud_score": fraud_result.fraud_score, "signals": [s.get("signal_id") for s in fraud_result.to_dict().get("signals", [])]},
        ))

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

        # Decision ledger — GL mapper choice (CODE membrane)
        if draft_placeholder and draft_placeholder.lines:
            gl_inference: List[Dict[str, Any]] = []
            for dl in draft_placeholder.lines:
                for p in dl.postings:
                    gl_inference.append({
                        "input": getattr(dl, "line_id", "?"),
                        "rule": "semantic GL matching via coa_store",
                        "output": f"{p.account_number} {p.account_name} ({p.fund_name})",
                    })
            _ledger_append(job.church_id, LedgerEntry(
                entry_id=str(uuid.uuid4()),
                decision_id=f"{job.job_id}:gl_mapping",
                category=DecisionCategory.CODE,
                timestamp=datetime.utcnow(),
                authoring_actor={"actor_type": "pipeline", "actor_id": "gl_mapper", "authority_tier": 0},
                policy_invoked="gl_account_mapper",
                evidence_refs=[job.job_id],
                cited_event_ids=[context_event_id] if context_event_id else [],
                inference_chain=gl_inference,
                conclusion=f"Mapped {len(draft_placeholder.lines)} line(s) to GL accounts.",
                alternatives=[
                    {"description": "Manual GL selection", "rejection_rationale": "Automated mapping applied; HITL escalated if reviewer verdict is REJECT"},
                ],
                outcome=DecisionOutcome.ACCEPTED,
                metadata={"lines_mapped": len(draft_placeholder.lines)},
            ))

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


def _evaluate_context_for_routing(job: ProcessingJob, context_event_id: Optional[str] = None) -> tuple[bool, List[str]]:
    """Phase 5d: Evaluate context signals to determine if routing is necessary.

    Returns: (should_route, signals) where should_route=True means the item needs
    human approval, and signals is a list of reasons (empty if no signals raised).

    The vision says routing should fire only on genuine signals:
    - Policy conflict (e.g., fund restriction violation)
    - Budget overage (account is over budget)
    - Critical signals from risk/fraud assessment
    - Missing contract or pricing history

    Otherwise, even if an approval chain is configured, the rote approval is skipped.
    """
    signals: List[str] = []

    # Signal 1: Policy conflict from risk assessment
    if job.risk_assessment and job.risk_assessment.get("risk_level") in ["CRITICAL", "HIGH"]:
        signals.append(f"Risk signal: {job.risk_assessment.get('risk_level')}")

    # Signal 2: Policy conflict from fraud assessment
    if job.fraud_assessment and job.fraud_assessment.get("fraud_level") in ["CRITICAL", "HIGH"]:
        signals.append(f"Fraud signal: {job.fraud_assessment.get('fraud_level')}")

    # Signal 3: Budget overage
    if job.budget_check:
        for bc in job.budget_check:
            if bc.ytd_actual and bc.annual_budget:
                ytd = Decimal(str(bc.ytd_actual or 0))
                annual = Decimal(str(bc.annual_budget or 0))
                if annual > 0 and ytd >= annual:
                    signals.append(f"Budget OVER for {bc.account_number}")

    # Signal 4: Escalation reasons from review
    if job.reviewed_allocations and job.reviewed_allocations.escalation_items:
        signals.append(f"Manual escalation: {len(job.reviewed_allocations.escalation_items)} items")

    # If any signal raised, route to human approval
    should_route = len(signals) > 0
    return should_route, signals


async def _maybe_request_budget_owner_approval(
    job: ProcessingJob,
    reviewed: ReviewedAllocations,
) -> bool:
    """FR-05.2: Context-aware approval routing.

    Phase 5d vision: routing fires only on genuine signals (policy conflict,
    budget overage, risk/fraud, manual escalation). If no signals, skip
    approval even if a chain is configured — 80% of rote approvals disappear.

    If context evaluation says routing is necessary, scan draft allocations,
    find a configured approval chain, mint approval tokens, email the budget
    owner, set the job to PENDING_BUDGET_OWNER, and return True.
    Otherwise return False.
    """
    if not job.draft_allocations or not job.invoice_document:
        return False

    # Phase 5d: Evaluate context signals first
    should_route, routing_signals = _evaluate_context_for_routing(job)
    if not should_route:
        # No signals raised; skip approval and auto-post
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
        "routing_signals": routing_signals,  # Phase 5d: context signals that triggered routing
    })

    # Decision ledger — approval chain resolution (APPROVE membrane)
    _ledger_append(job.church_id, LedgerEntry(
        entry_id=str(uuid.uuid4()),
        decision_id=f"{job.job_id}:approval_routing",
        category=DecisionCategory.APPROVE,
        timestamp=datetime.utcnow(),
        authoring_actor={"actor_type": "pipeline", "actor_id": "approval_chain_resolver", "authority_tier": 0},
        policy_invoked="approval_chain_resolver",
        evidence_refs=[job.job_id, chain.chain_id],
        inference_chain=[
            {"input": f"GL={matched_gl.account_number}", "rule": "exact → range → wildcard pattern match on ApprovalChain.gl_pattern", "output": f"chain={chain.chain_id}"},
            {"input": f"chain={chain.chain_id}", "rule": "primary_approver lookup", "output": f"approver={chain.primary_approver_email}"},
        ],
        conclusion=(
            f"Routed to approval chain '{chain.chain_id}' "
            f"(approver: {chain.primary_approver_email}) "
            f"based on GL account {matched_gl.account_number} {matched_gl.account_name}."
        ),
        alternatives=[
            {"description": "Auto-approve without human review", "rejection_rationale": "Approval chain configured; budget-owner sign-off required by policy"},
        ],
        outcome=DecisionOutcome.DELEGATED,
        metadata={"chain_id": chain.chain_id, "approver_email": chain.primary_approver_email, "gl_account": matched_gl.account_number},
    ))
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
    job = processing_job_store.get_job(job_id)
    if not job:
        return
    if job.status != ProcessingStatus.TREASURER_APPROVED:
        return
    if job.reviewed_allocations is None:
        return
    await _build_and_emit(job, job.reviewed_allocations, job.hitl_decisions)


async def submit_hitl_decisions(job_id: str, decisions: HITLDecisions) -> None:
    """Resume the pipeline after HITL review gate."""
    job = processing_job_store.get_job(job_id)
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
            loop = asyncio.get_event_loop()
            for jl in job.journal_entry.lines:
                debit = Decimal(jl.debit or Decimal("0"))
                if debit > Decimal("0"):
                    # Atomic increment with optimistic locking — prevents lost
                    # updates when concurrent invoices touch the same account.
                    new_total = await loop.run_in_executor(
                        None,
                        coa_store.update_ytd_actual,
                        job.church_id,
                        jl.account_number,
                        ctx.fiscal_year,
                        debit,
                    )
                    ctx.ytd_actuals[jl.account_number] = new_total
                    updates[jl.account_number] = new_total
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

    # Persist final mutations (journal_entry, audit_log appends after EMITTED).
    _persist_job(job)
