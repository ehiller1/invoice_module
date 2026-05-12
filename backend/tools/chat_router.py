"""Chat router — routes user questions to relevant agent context and calls Anthropic.

Phase 2.8 adds an intent classification step. When the user expresses a
"create manual JE" intent, the router uses Claude to extract the slot values
(from_account_hint, to_account_hint, amount, fund_hint, memo), resolves the
account hints via semantic search, and returns a draft JournalEntry payload
for confirmation in the chat rail.

Phase 2.9 wires per-church KB hits into every chat turn so Claude can cite
parish-specific guidance alongside denominational canon.
"""
from __future__ import annotations
import json
import logging
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .skill_registry import get_registry

logger = logging.getLogger(__name__)

# Denomination skill map
_DENOM_SKILL = {
    "UMC": "denomination_umc",
    "EPISCOPAL": "denomination_episcopal",
    "CATHOLIC_PARISH": "denomination_catholic_parish",
    "BAPTIST_INDEPENDENT": "denomination_baptist",
    "PRESBYTERIAN_PCUSA": "denomination_presbyterian",
}

_TOPIC_SKILLS = {
    "classif": "line_item_classifier",
    "gl map": "gl_account_mapper",
    "account map": "gl_account_mapper",
    "journal": "journal_entry_builder",
    "fraud": "fraud_detector",
    "risk": "risk_assessor",
    "escalat": "allocation_reviewer",
    "hitl": "hitl_invoice_gate",
    "fund": "coa_reference_loader",
    "restrict": "coa_reference_loader",
    "denomination": None,  # handled separately
    "apportionment": None,
    "per capita": None,
    "cooperative": None,
    "housing": "expense_taxonomy_v1",
}


# ---------------------------------------------------------------------------
# Intent classification (FR-06.2)
# ---------------------------------------------------------------------------

# Heuristic keywords that strongly signal a "create JE" intent. These are used
# both as a fast-path classifier (so we don't have to call Claude in tests) and
# as a hint to the LLM in the prompt.
_CREATE_JE_PATTERNS = [
    r"\bcreate\s+(?:a\s+)?journal\s+entry\b",
    r"\bcreate\s+(?:a\s+)?j\.?\s*e\.?\b",
    r"\bmake\s+(?:a\s+)?journal\s+entry\b",
    r"\bmake\s+(?:a\s+)?j\.?\s*e\.?\b",
    r"\brecord\s+(?:a\s+)?journal\s+entry\b",
    r"\bbook\s+(?:a\s+)?journal\s+entry\b",
    # Phase 5b: catch "draft a JE …" — this was the Flow 3 phrasing-A miss
    # that fell through to QA and produced hallucinated GL accounts.
    r"\bdraft\s+(?:a\s+|me\s+a\s+)?journal\s+entry\b",
    r"\bdraft\s+(?:a\s+|me\s+a\s+)?j\.?\s*e\.?\b",
    r"\bdraft\s+(?:me\s+)?(?:an?\s+)?entry\s+(?:for|to)\b",
    r"\bpost\s+(?:a\s+|the\s+)?(?:journal\s+)?entry\b",
    r"\btransfer\s+\$?\d",
    r"\brecord\s+a\s+transfer\b",
    r"\bmake\s+an?\s+entry\s+(?:for|to)\b",
    r"\bjournalize\b",
]


INTENT_CREATE_MANUAL_JE = "CREATE_MANUAL_JE"
INTENT_QA = "QA"


def classify_intent(question: str) -> str:
    """Return the high-level intent for a chat turn.

    Currently only distinguishes CREATE_MANUAL_JE vs general QA. Uses regex
    heuristics so no LLM call is required for classification.
    """
    if not question:
        return INTENT_QA
    q = question.lower()
    for pat in _CREATE_JE_PATTERNS:
        if re.search(pat, q):
            return INTENT_CREATE_MANUAL_JE
    return INTENT_QA


# ---------------------------------------------------------------------------
# Slot extraction for CREATE_MANUAL_JE
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(r"\$?\s*([0-9][\d,]*(?:\.\d+)?)")


def _extract_amount_heuristic(question: str) -> Optional[Decimal]:
    m = _AMOUNT_RE.search(question)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        return Decimal(raw)
    except Exception:
        return None


def _extract_from_to_heuristic(question: str) -> Tuple[str, str]:
    """Best-effort slot extraction without an LLM. Returns (from_hint, to_hint)."""
    q = question
    # Look for "from X to Y"
    m = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:\.|$|,| for | with )", q, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Look for "transfer ... to Y" (debit Y, credit unknown)
    m = re.search(r"\bto\s+(.+?)(?:\.|$|,| for | with )", q, re.I)
    if m:
        return "", m.group(1).strip()
    return "", ""


def _extract_je_slots_with_claude(question: str, ctx: Optional[Any]) -> Dict[str, Any]:
    """Use Claude with structured output to extract JE slot values.

    Falls back to regex heuristics if no API key or the call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    fallback = {
        "from_account_hint": "",
        "to_account_hint": "",
        "amount": None,
        "fund_hint": None,
        "memo": question.strip(),
    }
    fhint, thint = _extract_from_to_heuristic(question)
    fallback["from_account_hint"] = fhint
    fallback["to_account_hint"] = thint
    amt = _extract_amount_heuristic(question)
    if amt is not None:
        fallback["amount"] = float(amt)

    if not api_key:
        return fallback
    try:
        import anthropic  # type: ignore
    except ImportError:
        return fallback

    system = (
        "You are an extractor for accounting journal-entry intents. "
        "Given a user's natural-language request to create a JE, extract the "
        "slot values as STRICT JSON with these fields: "
        "from_account_hint (str), to_account_hint (str), amount (number), "
        "fund_hint (str|null), memo (str). "
        "Do NOT include explanation. Output JSON only."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": question}],
        )
        text = msg.content[0].text if msg.content else ""
        # Find first {...} block
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return fallback
        data = json.loads(m.group(0))
        # Coerce types
        out = dict(fallback)
        for k in ("from_account_hint", "to_account_hint", "memo"):
            v = data.get(k)
            if v is not None:
                out[k] = str(v)
        if data.get("amount") is not None:
            try:
                out["amount"] = float(data["amount"])
            except Exception:
                pass
        if data.get("fund_hint") is not None:
            out["fund_hint"] = str(data["fund_hint"]) or None
        return out
    except Exception:
        return fallback


def _resolve_account(church_id: str, hint: str,
                     fund_filter: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Use coa_store.semantic_search to resolve a free-text account hint."""
    if not hint or not church_id:
        return None
    from . import coa_store
    results = coa_store.semantic_search(
        church_id, query=hint, k=1, fund_filter=fund_filter,
    )
    if not results:
        return None
    return results[0]


def _build_je_from_slots(
    church_id: str,
    slots: Dict[str, Any],
    ctx: Optional[Any],
    original_question: str,
) -> Dict[str, Any]:
    """Resolve account hints and build a JournalEntry draft from pre-extracted slots.

    Separated from slot extraction so the unified LLM path in route_question can
    feed slots directly without triggering a second LLM call.
    """
    from ..models.schemas import JournalEntry, JournalEntryLine, JEStatus

    errors: List[str] = []
    amount = slots.get("amount")
    if amount is None or float(amount) <= 0:
        errors.append("Could not determine the amount from your request.")
    from_hint = slots.get("from_account_hint") or ""
    to_hint = slots.get("to_account_hint") or ""
    if not from_hint:
        errors.append("Could not determine the source (credit) account.")
    if not to_hint:
        errors.append("Could not determine the destination (debit) account.")

    # Resolve fund hint → fund_id filter (best-effort)
    fund_filter: Optional[List[str]] = None
    fund_hint = slots.get("fund_hint")
    if fund_hint and ctx is not None:
        try:
            funds = getattr(ctx, "funds", []) or []
            for f in funds:
                fid = getattr(f, "fund_id", "")
                fname = getattr(f, "fund_name", "")
                if fund_hint.upper() in (fid.upper(), fname.upper()):
                    fund_filter = [fid]
                    break
        except Exception:
            fund_filter = None

    # Phase 5b: ground every account reference against the seeded CoA before
    # falling through to semantic search. A purely-numeric hint that doesn't
    # exist in the seeded CoA is a hard error — never silently substitute.
    from ..events.coa_grounding import ground_je_slot

    debit_acct, debit_err = ground_je_slot(ctx, to_hint, fund_filter=fund_filter)
    credit_acct, credit_err = ground_je_slot(ctx, from_hint, fund_filter=fund_filter)

    if debit_acct is None and not debit_err:
        debit_acct = _resolve_account(church_id, to_hint, fund_filter=fund_filter)
    if credit_acct is None and not credit_err:
        credit_acct = _resolve_account(church_id, from_hint, fund_filter=fund_filter)

    if debit_err:
        errors.append(debit_err)
    elif to_hint and debit_acct is None:
        errors.append(f"Could not find a GL account matching {to_hint!r}.")
    if credit_err:
        errors.append(credit_err)
    elif from_hint and credit_acct is None:
        errors.append(f"Could not find a GL account matching {from_hint!r}.")

    if errors or amount is None or debit_acct is None or credit_acct is None:
        return {
            "type": "manual_je_draft",
            "je_draft": None,
            "confirmation_required": False,
            "summary": "Could not draft a manual journal entry from that request.",
            "errors": errors,
        }

    amount_dec = Decimal(str(amount))
    today = date.today()
    fiscal_year = getattr(ctx, "fiscal_year", today.year) if ctx else today.year
    period = f"{today.year}-{today.month:02d}"
    memo = (slots.get("memo") or original_question.strip())[:140]

    debit_line = JournalEntryLine(
        sequence=1,
        account_number=str(debit_acct.get("account_number", "")),
        account_name=str(debit_acct.get("account_name", "")),
        fund_id=str(debit_acct.get("fund_id", "")),
        fund_name=str(debit_acct.get("fund_name", "")),
        debit=amount_dec,
        credit=Decimal("0"),
        memo=memo,
    )
    credit_line = JournalEntryLine(
        sequence=2,
        account_number=str(credit_acct.get("account_number", "")),
        account_name=str(credit_acct.get("account_name", "")),
        fund_id=str(credit_acct.get("fund_id", "")),
        fund_name=str(credit_acct.get("fund_name", "")),
        debit=Decimal("0"),
        credit=amount_dec,
        memo=memo,
    )

    entry_id = f"JE-MANUAL-{uuid.uuid4().hex[:8].upper()}"
    je = JournalEntry(
        entry_id=entry_id,
        church_id=church_id,
        fiscal_year=int(fiscal_year),
        accounting_period=period,
        entry_date=today,
        reference=f"MANUAL-{entry_id[-8:]}",
        vendor_name="Manual Entry",
        description=memo,
        status=JEStatus.DRAFT,
        lines=[debit_line, credit_line],
        total_debits=amount_dec,
        total_credits=amount_dec,
        balanced=True,
        audit_trail_url="",
    )

    summary = (
        f"Created draft JE: Debit {debit_line.account_name} ${amount_dec:,.2f}, "
        f"Credit {credit_line.account_name} ${amount_dec:,.2f}"
    )

    # Phase 5b: emit a ClassificationProposed event so the slot resolution
    # is auditable in the event log. This is *proposed*, not posted —
    # TransactionPosted only fires after the user confirms the draft.
    try:
        from ..events.emitter import emit_event
        from ..events.schemas import EventType, FinancialEvent, TagKind
        ev = FinancialEvent(
            event_type=EventType.CLASSIFICATION_PROPOSED,
            church_id=church_id,
            payload={
                "draft_entry_id": entry_id,
                "amount": str(amount_dec),
                "from_account_hint": from_hint,
                "to_account_hint": to_hint,
                "resolved_debit": debit_line.account_number,
                "resolved_credit": credit_line.account_number,
                "memo": memo,
                "source": "chat_router",
            },
            correlation_id=entry_id,
        )
        ev.add_tag(TagKind.ACCOUNT, debit_line.account_number)
        ev.add_tag(TagKind.ACCOUNT, credit_line.account_number)
        if debit_line.fund_id:
            ev.add_tag(TagKind.FUND, debit_line.fund_id)
        emit_event(ev)
    except Exception:
        # Event emission must never break the user-facing draft flow.
        pass

    return {
        "type": "manual_je_draft",
        "je_draft": json.loads(je.model_dump_json()),
        "confirmation_required": True,
        "summary": summary,
        "errors": [],
    }


def build_manual_je_draft(
    church_id: str,
    question: str,
    ctx: Optional[Any] = None,
) -> Dict[str, Any]:
    """Extract slots from the question via LLM, then resolve accounts and build a draft JE.

    Returns a dict suitable as a chat reply payload:
        {
            "type": "manual_je_draft",
            "je_draft": {... JournalEntry .model_dump() ...},
            "confirmation_required": True,
            "summary": "Created draft JE: ...",
            "errors": [...]
        }
    """
    slots = _extract_je_slots_with_claude(question, ctx)
    return _build_je_from_slots(church_id, slots, ctx, question)


# ---------------------------------------------------------------------------
# QA prompt assembly
# ---------------------------------------------------------------------------

def _build_system_prompt(job: Optional[Any], kb_hits: Optional[List[Any]] = None) -> str:
    registry = get_registry()
    qa_skill = registry.load_body("agent_qa_interface") if registry.get("agent_qa_interface") else ""

    system = (
        "You are the Books assistant — an expert church accountant for a parish using "
        "the Books platform. You have deep knowledge of nonprofit fund accounting "
        "(GAAP ASC 958), church-denomination-specific accounting rules, and the Books "
        "pipeline.\n\n"
        "You can answer questions in three modes, and you should pick the right mode "
        "based on the question:\n"
        "  1. **Invoice/job triage** — when a specific job context is provided, explain "
        "     classification rationale, GL account selection, risk scores, fraud signals, "
        "     fund restrictions, and journal entry construction.\n"
        "  2. **Financial position** — when the user asks about current cash, balances, "
        "     net assets, fund position, or 'how are we doing right now', use the "
        "     'Current financial position' snapshot in the user context. Always state "
        "     the basis (cash vs accrual) and the as-of date. Show confidence ranges "
        "     instead of point estimates when the underlying numbers carry uncertainty.\n"
        "  3. **General accounting Q&A** — for everything else, answer as a church "
        "     accountant would.\n\n"
        "Rules:\n"
        "- Cite specific values from the supplied context whenever possible.\n"
        "- When uncertainty exists, acknowledge it explicitly and propose what would "
        "  tighten the answer.\n"
        "- Use plain English; define accounting terms inline.\n"
        "- Do not refuse a question because it's outside the invoice pipeline. If you "
        "  lack data, say what you'd need.\n\n"
    )
    if qa_skill:
        system += f"## Agent Q&A Interface Protocol\n{qa_skill[:1500]}\n\n"

    if kb_hits:
        system += "## Relevant church accounting reference (cite when used):\n"
        for h in kb_hits:
            cite = getattr(h, "citation", "") or "Reference"
            text = (getattr(h, "text", "") or "")[:600]
            system += f"- [{cite}] {text}\n"
        system += (
            "\nWhen any of the above passages are used in your answer, cite them "
            "inline using the bracketed citation labels.\n\n"
        )
    return system


def _build_financial_position_snippet(ctx: Optional[Any]) -> str:
    """Compose a balance-sheet-flavoured snapshot for the LLM prompt.

    Delegates to backend.routes.financial_position.compute_position so the
    chat snippet and the dashboard card show the *same* numbers. Returns
    an empty string when no church_id is available.
    """
    if ctx is None:
        return ""
    church_id = getattr(ctx, "church_id", None)
    if not church_id:
        return ""
    try:
        from ..routes.financial_position import compute_position
        snap = compute_position(church_id)
    except Exception:
        snap = None
    if not snap:
        return ""

    totals = snap.get("totals", {}) or {}
    funds = snap.get("funds", []) or []
    out = ["## Current financial position (latest available snapshot)"]
    out.append(f"- As-of: {snap.get('as_of', '?')} (basis: {snap.get('basis', 'ledger_balance')})")
    out.append(f"- Total fund balance: ${totals.get('total_fund_balance', 0):,.0f}")
    out.append(f"  - Unrestricted:           ${totals.get('unrestricted', 0):,.0f}")
    out.append(f"  - Temporarily restricted: ${totals.get('temporarily_restricted', 0):,.0f}")
    out.append(f"  - Permanently restricted: ${totals.get('permanently_restricted', 0):,.0f}")
    if funds:
        out.append("- Fund-level detail (largest first):")
        for f in funds[:8]:
            name = f.get('fund_name', '?')
            rc = f.get('restriction_class', '?')
            cur = f.get('current_balance', 0)
            opening = f.get('opening_balance', cur)
            je_net = f.get('je_net', 0.0)
            je_n = f.get('posted_je_count', 0)
            if je_n > 0:
                sign = '+' if je_net >= 0 else '-'
                je_label = f"opening ${opening:,.0f} + {je_n} posted JE {sign}${abs(je_net):,.0f}"
                out.append(f"  - {name}: ${cur:,.0f} ({rc}) [{je_label}]")
            else:
                out.append(f"  - {name}: ${cur:,.0f} ({rc})")
    conf = snap.get("confidence", {}) or {}
    out.append(f"- Confidence: fund-level {conf.get('fund_level', 'HIGH')}, GL roll-up {conf.get('gl_rollup', 'MEDIUM')}.")
    out.append(f"- {conf.get('as_of_basis', 'ledger snapshot, not a closed-period statement')}.")
    return "\n".join(out)


def _build_user_context(question: str, job: Optional[Any], ctx: Optional[Any] = None) -> str:
    """Build a rich context string from job state for the LLM prompt.

    `ctx` is the AccountingContext — passed in directly so callers without a
    job (Flow 16 "books-as-of-now") still get a real financial-position
    snippet appended.
    """
    parts: List[str] = [f"## User Question\n{question}\n"]

    if not job:
        # No job context — but we still know the church. Include a
        # financial-position snapshot when an AccountingContext is available
        # so Flow 16 questions ("what's our financial position?") get a real
        # answer instead of a "no context" stub.
        snippet = _build_financial_position_snippet(ctx)
        if snippet:
            parts.append("\n" + snippet)
            parts.append("\n## Answering guidance")
            parts.append(
                "If the user asks about current financial position, cash, fund balances, "
                "net assets, or 'how are we doing right now', cite the snapshot above and "
                "flag any number whose basis or confidence is less than HIGH. Show ranges "
                "or confidence bands instead of point estimates when uncertainty exists."
            )
        else:
            parts.append("\n## Context\nNo specific job context provided. Answer based on general EIME/accounting knowledge.")
        return "\n".join(parts)

    # Determine which skills to load based on question keywords
    registry = get_registry()
    q_lower = question.lower()
    loaded_skills: List[str] = []

    for kw, skill_name in _TOPIC_SKILLS.items():
        if kw in q_lower and skill_name and skill_name not in loaded_skills:
            skill_body = registry.load_body(skill_name) if registry.get(skill_name) else None
            if skill_body:
                parts.append(f"\n## Skill Context: {skill_name}\n{skill_body[:1200]}")
                loaded_skills.append(skill_name)

    # Denomination skill
    ctx = getattr(job, "accounting_context", None)
    denom = str(getattr(ctx, "denomination_type", "")).upper() if ctx else ""
    if denom and ("denomination" in q_lower or "apportionment" in q_lower
                  or "per capita" in q_lower or "cooperative" in q_lower):
        denom_skill = _DENOM_SKILL.get(denom)
        if denom_skill and denom_skill not in loaded_skills:
            body = registry.load_body(denom_skill) if registry.get(denom_skill) else None
            if body:
                parts.append(f"\n## Denomination Skill Context: {denom_skill}\n{body[:1500]}")

    # Job state
    parts.append(f"\n## Job State")
    parts.append(f"- Job ID: {job.job_id}")
    parts.append(f"- Status: {job.status}")
    parts.append(f"- Filename: {job.filename}")

    if job.invoice_document:
        inv = job.invoice_document
        parts.append(f"\n## Invoice")
        parts.append(f"- Vendor: {inv.vendor_name}")
        parts.append(f"- Invoice #: {inv.invoice_number}")
        parts.append(f"- Date: {inv.invoice_date}")
        parts.append(f"- Total: ${inv.total_amount}")
        parts.append(f"- Document Type: {inv.document_type}")
        if inv.line_items:
            parts.append(f"- Line Items ({len(inv.line_items)}):")
            for li in inv.line_items:
                parts.append(f"  • {li.line_id}: {li.description} — ${li.amount}")

    if job.accounting_context:
        ac = job.accounting_context
        parts.append(f"\n## Accounting Context")
        parts.append(f"- Church: {ac.church_name}")
        parts.append(f"- Denomination: {ac.denomination_type}")
        parts.append(f"- Capitalisation Threshold: ${ac.capitalisation_threshold_usd}")
        parts.append(f"- Funds: {', '.join(f.fund_name for f in ac.funds)}")

    if job.classified_items:
        parts.append(f"\n## Classification Results")
        for cl in job.classified_items:
            flags = []
            if cl.flags.requires_hitl:
                flags.append("HITL_REQUIRED")
            if cl.flags.capitalise:
                flags.append("CAPITALISE")
            if cl.flags.is_housing_related:
                flags.append("HOUSING")
            if cl.flags.is_missions_passthrough:
                flags.append("MISSIONS_PASSTHROUGH")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            parts.append(
                f"  • {cl.line_id}: {cl.description[:50]} → {cl.expense_category} "
                f"(conf={cl.confidence:.2f}){flag_str}"
            )
            parts.append(f"    Rationale: {cl.classification_rationale[:100]}")

    if job.draft_allocations:
        parts.append(f"\n## Draft GL Allocations")
        for dl in job.draft_allocations.lines:
            parts.append(f"  • {dl.line_id}: balanced={dl.balanced}")
            for p in dl.postings:
                side = f"DR ${p.debit_amount}" if p.debit_amount else f"CR ${p.credit_amount}"
                parts.append(f"    {p.account_number} {p.account_name} ({p.fund_name}) {side}")

    if job.reviewed_allocations:
        rv = job.reviewed_allocations
        parts.append(f"\n## Review Results")
        parts.append(f"- Overall Verdict: {rv.overall_verdict}")
        if rv.escalation_items:
            parts.append(f"- Escalation Items: {'; '.join(rv.escalation_items)}")
        if rv.review_notes:
            parts.append(f"- Review Notes: {rv.review_notes}")

    if hasattr(job, "risk_assessment") and job.risk_assessment:
        ra = job.risk_assessment
        parts.append(f"\n## Risk Assessment")
        parts.append(f"- Level: {ra.get('risk_level', '—')}  Score: {ra.get('risk_score', 0):.3f}")
        if ra.get("recommendations"):
            for r in ra["recommendations"]:
                parts.append(f"  → {r}")

    if hasattr(job, "fraud_assessment") and job.fraud_assessment:
        fa = job.fraud_assessment
        parts.append(f"\n## Fraud Assessment")
        parts.append(f"- Level: {fa.get('fraud_level', '—')}  Score: {fa.get('fraud_score', 0):.3f}")
        parts.append(f"- Action: {fa.get('recommended_action', '—')}")
        for sig in fa.get("signals", []):
            parts.append(f"  ⚠ [{sig['category']}] {sig['signal_id']}: {sig['description']}")

    if job.journal_entry:
        je = job.journal_entry
        parts.append(f"\n## Journal Entry")
        parts.append(f"- Entry ID: {je.entry_id}  Status: {je.status}")
        parts.append(f"- Total Debits: ${je.total_debits}  Credits: ${je.total_credits}  Balanced: {je.balanced}")
        for ln in je.lines:
            side = f"DR ${ln.debit}" if ln.debit else f"CR ${ln.credit}"
            parts.append(f"  [{ln.sequence}] {ln.account_number} {ln.account_name} {side}")

    if job.hitl_decisions:
        parts.append(f"\n## HITL Decisions")
        for d in job.hitl_decisions.line_decisions:
            parts.append(f"  • {d.line_id}: {d.action} by {d.reviewer_id} — {d.notes or '(no notes)'}")

    return "\n".join(parts)


async def route_question(
    question: str,
    job: Optional[Any] = None,
    church_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Route a user question via a single LLM call.

    One Claude call handles everything: intent classification, JE slot extraction
    (when the user wants to create a journal entry), and QA answers (otherwise).
    The LLM is always grounded in the seeded chart of accounts so both
    "Draft a JE for me" and "Create a journal entry:" reach the same code path
    and produce the same structured draft.

    The response always has the shape:
        {
          "intent": "CREATE_MANUAL_JE" | "QA",
          "answer": str,
          "je_draft": dict | None,          # present only for JE intents
          "confirmation_required": bool,
          ...
        }
    """
    # Effective church_id: explicit > job's church_id
    effective_church = church_id
    if effective_church is None and job is not None:
        ctx_obj = getattr(job, "accounting_context", None)
        effective_church = getattr(ctx_obj, "church_id", None) if ctx_obj else None

    # Load CoA context (needed for JE resolution and for grounding QA answers)
    ctx: Optional[Any] = None
    if job is not None:
        ctx = getattr(job, "accounting_context", None)
    if ctx is None and effective_church:
        try:
            from . import coa_store
            ctx = coa_store.load_accounting_context(effective_church)
        except Exception:
            ctx = None

    # Fast regex path: unambiguous create-JE phrasing → skip classification LLM call
    if classify_intent(question) == INTENT_CREATE_MANUAL_JE:
        draft = build_manual_je_draft(
            church_id=effective_church or "",
            question=question,
            ctx=ctx,
        )
        return {
            "answer": draft["summary"],
            "intent": INTENT_CREATE_MANUAL_JE,
            "type": draft["type"],
            "je_draft": draft.get("je_draft"),
            "confirmation_required": draft.get("confirmation_required", False),
            "errors": draft.get("errors", []),
            "skills_consulted": ["journal_entry_builder"],
            "model": None,
        }

    # ------------------------------------------------------------------ #
    # Unified LLM call — classifies intent AND either extracts JE slots   #
    # or answers the question, all in one round-trip.                     #
    # ------------------------------------------------------------------ #
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    kb_hits: List[Any] = []
    try:
        from . import knowledge_base
        # Phase 6: filter KB by church's denomination to avoid cross-denomination citations
        denomination = getattr(ctx, "denomination_type", None) if ctx else None
        kb_hits = knowledge_base.kb_search(
            question,
            church_id=effective_church,
            k=3,
            denomination=denomination
        )
    except Exception:
        kb_hits = []

    if not api_key:
        # Distinct error code so ops can grep for it; user sees a stable string.
        logger.error(
            "chat-assistant unavailable: ANTHROPIC_API_KEY is not set "
            "(error_code=assistant-unavailable:no-key)"
        )
        return {
            "answer": (
                "I can't answer questions right now — the conversational assistant is offline. "
                "Please reach out to your administrator and quote error code "
                "`assistant-unavailable:no-key`."
            ),
            "error_code": "assistant-unavailable:no-key",
            "intent": INTENT_QA,
            "skills_consulted": [],
            "kb_citations": [getattr(h, "citation", "") for h in kb_hits],
            "model": None,
        }

    try:
        import anthropic
    except ImportError:
        logger.error(
            "chat-assistant unavailable: anthropic Python package not installed "
            "(error_code=assistant-unavailable:no-package). Install with `uv pip install anthropic`."
        )
        return {
            "answer": (
                "I can't answer questions right now — the conversational assistant is offline. "
                "Please reach out to your administrator and quote error code "
                "`assistant-unavailable:no-package`."
            ),
            "error_code": "assistant-unavailable:no-package",
            "intent": INTENT_QA,
            "skills_consulted": [],
            "model": None,
        }

    # Build a CoA snippet so the LLM uses real GL account names/numbers
    coa_lines = ""
    if ctx is not None:
        try:
            accounts = getattr(ctx, "chart_of_accounts", []) or []
            coa_lines = "\n".join(
                f"{a.account_number} {a.account_name}" for a in accounts[:80]
            )
        except Exception:
            coa_lines = ""

    system = (
        "You are the EIME Agent — an expert church accountant specialising in "
        "nonprofit fund accounting (GAAP ASC 958).\n\n"
        "Respond with VALID JSON ONLY — no prose, no markdown fences.\n\n"
        "## Decision\n"
        "Decide whether the user wants to CREATE a journal entry or is asking a QUESTION.\n\n"
        "CREATE signals: draft, create, make, record, book, write up, post, journalize, "
        "transfer $X from Y to Z — anything that asks the system to produce a journal entry.\n\n"
        "## If CREATE — return:\n"
        '{"intent":"CREATE_MANUAL_JE","je_slots":{'
        '"from_account_hint":"<credit account description>",'
        '"to_account_hint":"<debit account description>",'
        '"amount":<number>,'
        '"fund_hint":<string or null>,'
        '"memo":"<short memo>"}}\n\n'
        "## If QUESTION — return:\n"
        '{"intent":"QA","answer":"<your answer>"}\n\n'
    )
    if coa_lines:
        system += (
            "## Chart of accounts (use EXACT account names and numbers for JEs):\n"
            + coa_lines + "\n\n"
        )
    if kb_hits:
        system += "## Relevant reference material:\n"
        for h in kb_hits:
            cite = getattr(h, "citation", "") or "Reference"
            text = (getattr(h, "text", "") or "")[:400]
            system += f"- [{cite}] {text}\n"

    user_context = _build_user_context(question, job, ctx)

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_context}],
    )
    raw = msg.content[0].text if msg.content else "{}"

    # Parse structured response
    try:
        m = re.search(r"\{.*\}", raw, re.S)
        data: Dict[str, Any] = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}

    llm_intent = data.get("intent", INTENT_QA)
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}

    registry = get_registry()
    skills_consulted = [
        s for s in ["agent_qa_interface", "line_item_classifier",
                     "gl_account_mapper", "fraud_detector", "risk_assessor"]
        if registry.get(s)
    ]

    if llm_intent == INTENT_CREATE_MANUAL_JE:
        # Use slots from the LLM response directly — no second LLM call needed
        je_slots = data.get("je_slots") or {}
        draft = _build_je_from_slots(
            church_id=effective_church or "",
            slots=je_slots,
            ctx=ctx,
            original_question=question,
        )
        return {
            "answer": draft["summary"],
            "intent": INTENT_CREATE_MANUAL_JE,
            "type": draft["type"],
            "je_draft": draft.get("je_draft"),
            "confirmation_required": draft.get("confirmation_required", False),
            "errors": draft.get("errors", []),
            "skills_consulted": ["journal_entry_builder"],
            "model": "claude-haiku-4-5-20251001",
            **usage,
        }

    # QA response — answer field from the LLM, or fall back to raw text
    answer = data.get("answer") or raw

    # Phase 5b: validate every GL account reference in the answer against
    # the seeded CoA. Hallucinated numbers (Flow 3: "5100 = Utilities" when
    # 5100 is Clergy Salary) get flagged and an explicit correction is
    # appended so the user is never silently misled.
    grounding_problems: List[Dict[str, Any]] = []
    if ctx is not None and answer:
        try:
            from ..events.coa_grounding import validate_text_grounding
            ok, grounding_problems = validate_text_grounding(ctx, answer)
            if not ok and grounding_problems:
                fixes: List[str] = []
                for p in grounding_problems:
                    if p["issue"] == "missing":
                        fixes.append(
                            f"⚠ GL account {p['reference']} is not in this "
                            f"church's chart of accounts."
                        )
                    elif p["issue"] == "label_mismatch":
                        fix = (
                            f"⚠ GL account {p['reference']} is "
                            f"'{p['actual_label']}' in this church's CoA, "
                            f"not '{p['claimed_label']}'."
                        )
                        if p.get("suggestion"):
                            sug = p["suggestion"]
                            fix += (
                                f" If you meant '{p['claimed_label']}', "
                                f"the correct number is "
                                f"{sug['account_number']} ({sug['account_name']})."
                            )
                        fixes.append(fix)
                if fixes:
                    answer = answer.rstrip() + "\n\n" + "\n".join(fixes)
        except Exception:
            grounding_problems = []

    return {
        "answer": answer,
        "intent": INTENT_QA,
        "skills_consulted": skills_consulted,
        "kb_citations": [getattr(h, "citation", "") for h in kb_hits],
        "grounding_problems": grounding_problems,
        "model": "claude-haiku-4-5-20251001",
        **usage,
    }
