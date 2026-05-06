"""Risk assessment tool — evaluates misclassification risk for invoice line items."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import List, Optional
import re

from ..models import AccountingContext, ClassifiedLineItem, DraftAllocations, DraftLineAllocation

AMBIGUOUS_KEYWORDS = frozenset([
    "miscellaneous", "misc", "various", "general", "supplies and labor",
    "as needed", "other", "general services", "assorted", "multiple items",
    "mixed", "sundry",
])

_ROUND_AMT = re.compile(r"^\d+\.00$")


@dataclass
class LineRisk:
    line_id: str
    risk_level: str
    risk_score: float
    flags: List[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskAssessment:
    risk_level: str
    risk_score: float
    per_line_risks: List[LineRisk] = field(default_factory=list)
    aggregate_flags: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _level(score: float) -> str:
    if score < 0.20:
        return "LOW"
    if score < 0.40:
        return "MEDIUM"
    if score < 0.65:
        return "HIGH"
    return "CRITICAL"


def assess_risk(
    classified: List[ClassifiedLineItem],
    draft: DraftAllocations,
    ctx: AccountingContext,
    vendor_history: Optional[List] = None,
) -> RiskAssessment:
    cap = float(ctx.capitalisation_threshold_usd)
    draft_map = {ln.line_id: ln for ln in draft.lines}
    per_line: List[LineRisk] = []

    for item in classified:
        score = 0.0
        flags: List[str] = []

        # Confidence base
        c = item.confidence
        if c >= 0.90:
            score += 0.05
        elif c >= 0.80:
            score += 0.25
        elif c >= 0.70:
            score += 0.50
        else:
            score += 0.75
            flags.append("low_confidence")

        dl: Optional[DraftLineAllocation] = draft_map.get(item.line_id)
        if dl:
            has_restricted = any(
                str(p.restriction_class) != "WITHOUT_RESTRICTION" for p in dl.postings
            )
            if has_restricted:
                score = min(1.0, score + 0.15)
                flags.append("restricted_fund_exposure")

            fund_ids = {p.fund_id for p in dl.postings if p.debit_amount > 0}
            if len(fund_ids) > 1:
                score = min(1.0, score + 0.10)
                flags.append("split_allocation")

        amt_f = float(item.amount)
        if cap * 0.85 <= amt_f <= cap * 1.15:
            score = min(1.0, score + 0.15)
            flags.append("near_capitalisation_threshold")

        if item.flags.is_housing_related:
            score = min(1.0, score + 0.10)
            flags.append("housing_allowance_irs_risk")

        desc_lower = item.description.lower()
        if any(kw in desc_lower for kw in AMBIGUOUS_KEYWORDS):
            score = min(1.0, score + 0.15)
            flags.append("ambiguous_description")

        if _ROUND_AMT.match(f"{item.amount:.2f}") and amt_f >= 500:
            score = min(1.0, score + 0.08)
            flags.append("round_number_amount")

        # Mitigators
        if c >= 0.95:
            score = max(0.0, score - 0.10)
        if item.flags.requires_hitl:
            score = max(0.0, score - 0.05)

        level = _level(score)
        if level == "CRITICAL":
            rec = "Do not post automatically — requires Finance Committee review"
        elif level == "HIGH":
            rec = "Require Treasurer sign-off before posting"
        elif level == "MEDIUM":
            rec = "Review classification rationale before posting"
        else:
            rec = "Standard automated approval appropriate"

        per_line.append(LineRisk(
            line_id=item.line_id,
            risk_level=level,
            risk_score=round(score, 3),
            flags=flags,
            recommendation=rec,
        ))

    scores = [lr.risk_score for lr in per_line]
    agg = max(scores) if scores else 0.0
    agg_level = _level(agg)

    agg_flags: List[str] = []
    recs: List[str] = []
    if any(lr.risk_level in ("HIGH", "CRITICAL") for lr in per_line):
        recs.append("One or more lines carry elevated misclassification risk — manual review recommended")
    if any("restricted_fund_exposure" in lr.flags for lr in per_line):
        recs.append("Verify restricted fund purpose alignment before posting")
        agg_flags.append("restricted_fund_exposure_present")
    if any("near_capitalisation_threshold" in lr.flags for lr in per_line):
        recs.append("Confirm capitalise vs. expense treatment for near-threshold amounts")

    return RiskAssessment(
        risk_level=agg_level,
        risk_score=round(agg, 3),
        per_line_risks=per_line,
        aggregate_flags=agg_flags,
        recommendations=recs,
    )
