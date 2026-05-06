"""Chat router — routes user questions to relevant agent context and calls Anthropic."""
from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional

from .skill_registry import get_registry

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


def _build_system_prompt(job: Optional[Any]) -> str:
    registry = get_registry()
    qa_skill = registry.load_body("agent_qa_interface") if registry.get("agent_qa_interface") else ""

    system = (
        "You are the EIME Agent Q&A Interface — an expert church accountant who explains "
        "the decisions made by the EIME invoice processing pipeline. You have deep knowledge "
        "of nonprofit fund accounting (GAAP ASC 958), church denomination-specific accounting "
        "rules, and the EIME pipeline architecture.\n\n"
        "Always cite specific values from the job context when available. "
        "When uncertainty exists, acknowledge it. "
        "Use plain English; define accounting terms inline.\n\n"
    )
    if qa_skill:
        system += f"## Agent Q&A Interface Protocol\n{qa_skill[:1500]}\n\n"
    return system


def _build_user_context(question: str, job: Optional[Any]) -> str:
    """Build a rich context string from job state for the LLM prompt."""
    parts: List[str] = [f"## User Question\n{question}\n"]

    if not job:
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
) -> Dict[str, Any]:
    """Route a user question, build context, call Anthropic, return answer."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "answer": (
                "The Agent Q&A interface requires an ANTHROPIC_API_KEY environment variable. "
                "Set it and restart the server to enable conversational agent interrogation."
            ),
            "skills_consulted": [],
            "model": None,
        }

    try:
        import anthropic
    except ImportError:
        return {
            "answer": "The anthropic package is not installed. Run: uv pip install anthropic",
            "skills_consulted": [],
            "model": None,
        }

    system = _build_system_prompt(job)
    user_context = _build_user_context(question, job)

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_context}],
    )

    answer = msg.content[0].text if msg.content else "(no response)"

    registry = get_registry()
    skills_consulted = [s for s in ["agent_qa_interface", "line_item_classifier",
                                     "gl_account_mapper", "fraud_detector", "risk_assessor"]
                        if registry.get(s)]

    return {
        "answer": answer,
        "skills_consulted": skills_consulted,
        "model": "claude-haiku-4-5-20251001",
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
    }
