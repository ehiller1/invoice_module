"""Allocation reviewer - implements the allocation_reviewer skill workflow."""
from __future__ import annotations
from decimal import Decimal
from typing import List

from ..models import (
    AccountingContext, ClassifiedLineItem, DraftAllocations,
    DraftLineAllocation, OverallVerdict, ReviewedAllocations, ReviewedLine,
    Verdict,
)


def review_allocations(
    draft: DraftAllocations,
    classified: List[ClassifiedLineItem],
    ctx: AccountingContext,
) -> ReviewedAllocations:
    """Implements allocation_reviewer skill steps 1-10."""
    classified_map = {c.line_id: c for c in classified}
    reviewed_lines: List[ReviewedLine] = []
    escalation_items: List[str] = []
    revision_items: List[str] = []

    housing_ytd = ctx.parsonage_allowance_used_ytd

    for line in draft.lines:
        verdict = Verdict.APPROVED
        reasons: List[str] = []
        ci = classified_map.get(line.line_id)

        # Step 2: fund restriction check per posting
        if ci and ci.flags.is_missions_passthrough and not ci.flags.requires_hitl:
            verdict = Verdict.ESCALATE
            reasons.append("Missions pass-through requires committee attestation.")

        # Step 3: restricted fund purpose match
        for posting in line.postings:
            if posting.restriction_class == "WITH_RESTRICTION_PURPOSE" and posting.debit_amount > 0:
                if ci:
                    eligible_fund_ids = ci.fund_eligibility
                    matching_funds = [f for f in ctx.funds if f.fund_id in eligible_fund_ids
                                      and f.restriction_class.value == "WITH_RESTRICTION_PURPOSE"]
                    if matching_funds and ci.expense_category not in (
                        matching_funds[0].purpose_description or ""
                    ):
                        # Soft check: if purpose description not populated, allow with ESCALATE
                        if matching_funds[0].purpose_description:
                            verdict = Verdict.ESCALATE
                            reasons.append(
                                f"Restricted fund {posting.fund_id} purpose mismatch with "
                                f"'{matching_funds[0].purpose_description}'."
                            )

        # Step 4: unbalanced line
        if not line.balanced:
            verdict = Verdict.ESCALATE
            reasons.append("Journal entry does not balance — manual correction required.")

        # Step 5: low-confidence escalation
        for posting in line.postings:
            if posting.confidence < 0.85 and posting.debit_amount > 0:
                verdict = Verdict.ESCALATE
                reasons.append(
                    f"Posting confidence {posting.confidence:.2f} < 0.85 on "
                    f"account {posting.account_number}."
                )

        # Step 6: housing allowance budget
        if ci and ci.flags.is_housing_related:
            line_housing_total = sum(
                (p.debit_amount for p in line.postings if p.debit_amount > 0), Decimal("0")
            )
            housing_ytd += line_housing_total
            if housing_ytd > ctx.parsonage_allowance_current_year:
                verdict = Verdict.ESCALATE
                reasons.append(
                    f"Housing allowance limit ${ctx.parsonage_allowance_current_year} would be exceeded. "
                    f"YTD after this line: ${housing_ytd}."
                )

        # Step 7: capitalisation check — amount > threshold mapped to operating account
        if ci and ci.flags.capitalise:
            for posting in line.postings:
                if posting.debit_amount > 0 and not posting.account_number.startswith("9"):
                    verdict = Verdict.REVISE
                    reasons.append(
                        f"Amount ${posting.debit_amount} exceeds capitalisation threshold "
                        f"${ctx.capitalisation_threshold_usd} — reclassify to fixed asset account (9200)."
                    )

        # Step 8: requires_hitl flag from classification
        if ci and ci.flags.requires_hitl and verdict == Verdict.APPROVED:
            verdict = Verdict.ESCALATE
            reasons.append("Classifier flagged low confidence or special handling required.")

        if verdict == Verdict.ESCALATE:
            escalation_items.append(line.line_id)
        elif verdict == Verdict.REVISE:
            revision_items.append(line.line_id)

        reviewed_lines.append(ReviewedLine(
            line_id=line.line_id,
            verdict=verdict,
            reasons=reasons,
        ))

    # Step 9: overall verdict
    if escalation_items:
        overall = OverallVerdict.ESCALATE
    elif revision_items:
        overall = OverallVerdict.PARTIAL
    else:
        overall = OverallVerdict.APPROVED

    return ReviewedAllocations(
        lines=reviewed_lines,
        overall_verdict=overall,
        escalation_items=escalation_items,
        revision_items=revision_items,
        review_notes=f"Auto-reviewed {len(reviewed_lines)} lines. "
                     f"{len(escalation_items)} escalated, {len(revision_items)} need revision.",
    )
