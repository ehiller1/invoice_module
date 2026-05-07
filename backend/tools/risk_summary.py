"""Plain-English risk summary — FR-04 + FR-09 (Phase 1.5/1.6).

Produces a one-paragraph human-readable explanation of why a reviewed line
needs attention. The summary must:
  1. Name the issue.
  2. Quantify the impact ($, % of budget, etc.).
  3. Cite the relevant rule (canon, budget threshold, GAAP).
  4. Suggest a next step.

Uses Claude Haiku (`claude-haiku-4-5-20251001`) when ANTHROPIC_API_KEY is set;
otherwise falls back to a deterministic template-based summary.

When a fund-restriction violation is detected and a `kb_search_func` is
provided, the top canon citation is woven into the summary text using the
`...per Title I, Canon 7...` style.
"""
from __future__ import annotations
import os
from typing import Any, Callable, List, Optional

from ..models import AccountingContext, ReviewedLine


# Tokens used to detect fund-restriction reasons (mirrors flow.py).
_FUND_RESTRICTION_MARKERS = (
    "RestrictionClass",
    "restricted",
    "WITH_RESTRICTION_PERMANENT",
    "WITH_RESTRICTION_PURPOSE",
    "fund restriction",
    "Fund restriction",
    "Missions pass-through",
)

_BUDGET_MARKERS = ("OVER BUDGET", "WARNING")
_CONFIDENCE_MARKERS = ("confidence", "Classifier flagged")


def _classify_reasons(reasons: List[str]) -> dict:
    """Bucket reasons by type, preserving order within each bucket."""
    buckets = {"budget": [], "restriction": [], "confidence": [], "other": []}
    for r in reasons:
        if any(m in r for m in _BUDGET_MARKERS):
            buckets["budget"].append(r)
        elif any(m in r for m in _FUND_RESTRICTION_MARKERS):
            buckets["restriction"].append(r)
        elif any(m in r for m in _CONFIDENCE_MARKERS):
            buckets["confidence"].append(r)
        else:
            buckets["other"].append(r)
    return buckets


def _deterministic_summary(
    line: ReviewedLine,
    ctx: Optional[AccountingContext],
    kb_citation: Optional[str] = None,
) -> str:
    """Template fallback used when the Anthropic SDK / API key is unavailable."""
    if not line.reasons:
        return (
            f"Why this needs review: line {line.line_id} was flagged for review "
            f"with verdict {line.verdict.value if hasattr(line.verdict, 'value') else line.verdict}, "
            f"but no specific reasons were captured. "
            f"Next step: ask the reviewer to confirm the GL coding manually."
        )

    buckets = _classify_reasons(line.reasons)

    lead_parts: List[str] = []
    if buckets["budget"]:
        lead_parts.append(buckets["budget"][0])
    if buckets["restriction"]:
        lead_parts.append(buckets["restriction"][0])
    if buckets["confidence"]:
        lead_parts.append(buckets["confidence"][0])
    if not lead_parts and buckets["other"]:
        lead_parts.append(buckets["other"][0])

    issue = " ".join(lead_parts)
    rule_clause = ""
    if buckets["budget"]:
        rule_clause = " per the church's annual budget threshold"
    if buckets["restriction"]:
        if kb_citation:
            rule_clause = f" per {kb_citation}"
        else:
            rule_clause = " per the donor-restricted-fund canon"
    if not rule_clause and buckets["confidence"]:
        rule_clause = " per the EIME 0.85 confidence threshold (FR-04 risk policy)"

    next_step = "Next step: route to the budget owner for an attestation review."
    if buckets["restriction"]:
        next_step = (
            "Next step: BLOCK the journal entry; require a vestry/committee "
            "resolution before any expenditure from this restricted fund."
        )
    elif buckets["budget"]:
        next_step = (
            "Next step: obtain budget-owner attestation OR re-allocate to an "
            "account with remaining budget."
        )
    elif buckets["confidence"]:
        next_step = (
            "Next step: have a finance reviewer confirm or override the GL coding."
        )

    return f"Why this needs review: {issue}{rule_clause}. {next_step}"


def _build_llm_prompt(
    line: ReviewedLine,
    ctx: Optional[AccountingContext],
    kb_citation: Optional[str],
) -> str:
    parts: List[str] = []
    parts.append(f"Line ID: {line.line_id}")
    parts.append(
        f"Verdict: {line.verdict.value if hasattr(line.verdict, 'value') else line.verdict}"
    )
    parts.append("Reasons (in priority order — budget, fund-restriction, confidence):")
    for r in line.reasons:
        parts.append(f"  - {r}")
    if ctx is not None:
        parts.append(f"\nDenomination: {ctx.denomination_type}")
        parts.append(f"Fiscal year: {ctx.fiscal_year}")
    if kb_citation:
        parts.append(f"\nApplicable canon citation: {kb_citation}")
    parts.append(
        "\nWrite ONE paragraph (3-4 sentences) explaining why this needs review. "
        "You MUST: (1) name the issue, (2) quantify the impact (use the dollar "
        "figures from the reasons), (3) cite the relevant rule (canon / budget "
        "threshold / GAAP — use the citation provided if any), (4) suggest the "
        "next step. Plain English. Begin with 'Why this needs review:'."
    )
    return "\n".join(parts)


def summarize_risk(
    line: ReviewedLine,
    ctx: Optional[AccountingContext] = None,
    kb_search_func: Optional[Callable[..., List[Any]]] = None,
) -> str:
    """Produce a one-paragraph plain-English risk summary for `line`.

    Args:
        line: The reviewed line whose reasons should be summarised.
        ctx:  Optional accounting context (used for denomination filtering of KB).
        kb_search_func: Optional callable matching the
            ``kb_search(query, k, denomination)`` signature from
            `backend.tools.knowledge_base`. When provided AND the line has a
            fund-restriction reason, the top canon citation is woven into the
            summary text.

    Returns:
        A single human-readable paragraph (no leading/trailing whitespace).
    """
    # Fold fund-restriction citation in, if a KB search function is supplied.
    kb_citation: Optional[str] = None
    has_restriction = any(
        any(m in r for m in _FUND_RESTRICTION_MARKERS) for r in line.reasons
    )
    if has_restriction and kb_search_func is not None:
        denom = None
        if ctx is not None:
            d = ctx.denomination_type
            denom = d.value if hasattr(d, "value") else str(d)
        # The query is the trigger described in the plan: "fund restriction <fund_id>"
        # We do not have direct access to the fund_id here, so use a generic
        # description seeded from the violating reason.
        violating = next(
            (r for r in line.reasons
             if any(m in r for m in _FUND_RESTRICTION_MARKERS)),
            "fund restriction",
        )
        try:
            hits = kb_search_func(
                query=f"fund restriction {violating}",
                k=2,
                denomination=denom,
            )
        except TypeError:
            # Caller may not accept the denomination kwarg; retry without.
            try:
                hits = kb_search_func(query=f"fund restriction {violating}", k=2)
            except Exception:
                hits = []
        except Exception:
            hits = []
        if hits:
            top = hits[0]
            citation = getattr(top, "citation", None) or (
                top.get("citation") if isinstance(top, dict) else None
            )
            if citation:
                kb_citation = str(citation)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _deterministic_summary(line, ctx, kb_citation)

    try:
        import anthropic  # type: ignore
    except ImportError:
        return _deterministic_summary(line, ctx, kb_citation)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=(
                "You are an EIME church accountant. Output exactly one short "
                "paragraph (no markdown, no bullets) suitable for display in a "
                "review modal. Cite canons or GAAP rules verbatim when given."
            ),
            messages=[{
                "role": "user",
                "content": _build_llm_prompt(line, ctx, kb_citation),
            }],
        )
        text = msg.content[0].text if msg.content else ""
        text = text.strip()
        # Belt-and-braces: ensure the citation actually appears in the output
        # when one was provided. If not, append it.
        if kb_citation and kb_citation not in text:
            text = text.rstrip(".") + f" (per {kb_citation})."
        if not text:
            return _deterministic_summary(line, ctx, kb_citation)
        return text
    except Exception:
        return _deterministic_summary(line, ctx, kb_citation)
