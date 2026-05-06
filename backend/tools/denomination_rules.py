"""Apply denomination-specific account/classification adjustments to classified line items."""
from __future__ import annotations
from typing import List

from ..models import AccountingContext, ClassifiedLineItem, DenominationType
from .skill_registry import get_registry

# Keyword → (expense_category override, account_hint, ministry_area)
_UMC_OVERRIDES = [
    (["apportionment", "world service", "episcopal fund", "annual conference assessment",
      "district superintendent", "ministerial education", "gc2024", "wespath invoice",
      "black college fund", "africa university"],
     "DENOMINATIONAL_ASSESSMENT", "8300"),
    (["wespath", "crsp", "umpip", "cpp health"],
     "BENEFITS", "5210"),
    (["human relations day", "one great hour", "native american ministries",
      "peace with justice", "world communion", "methodist student"],
     "MISSIONS", "2800"),
    (["seca reimbursement", "self-employment tax"],
     "SECA_REIMBURSEMENT", "5150"),
]

_EPISCOPAL_OVERRIDES = [
    (["diocesan assessment", "fair share", "the asking", "national church pledge",
      "pb&f", "diocesan pledge"],
     "DENOMINATIONAL_ASSESSMENT", "8410"),
    (["church pension", "cpg invoice", "cpf contribution", "ecca"],
     "BENEFITS", "5210"),
    (["rector's discretionary", "discretionary fund"],
     "PASTORAL_CARE", "6900"),
    (["endowment", "planned giving", "bequest"],
     "UNKNOWN", "1900"),
]

_CATHOLIC_OVERRIDES = [
    (["cathedraticum", "bishop's tax", "diocesan assessment", "mission assessment",
      "priest retirement fund"],
     "DENOMINATIONAL_ASSESSMENT", "8510"),
    (["peter's pence", "catholic relief", "operation rice bowl", "usccb", "bishop's appeal",
      "svdp", "st. vincent de paul", "home missions"],
     "MISSIONS", "2900"),
    (["mass intention", "mass stipend", "sacramental offering", "wedding offering",
      "funeral offering"],
     "UNKNOWN", "4500"),
    (["school subsidy", "school contribution", "ccd materials", "rcia", "religious education"],
     "CHILDREN_MINISTRY", "6200"),
]

_BAPTIST_OVERRIDES = [
    (["cooperative program", "cp giving", "state convention giving", "sbc cooperative",
      "associational missions"],
     "DENOMINATIONAL_ASSESSMENT", "8600"),
    (["lottie moon", "annie armstrong", "state mission offering", "world hunger",
      "namb offering", "imb offering"],
     "MISSIONS", "2610"),
    (["guidestone", "sbc annuity", "annuity board"],
     "BENEFITS", "5210"),
    (["deacon fund", "benevolence fund"],
     "BENEVOLENCE", "6910"),
    (["housing allowance", "pastor housing"],
     "CLERGY_HOUSING", "5101"),
]

_PRESBYTERIAN_OVERRIDES = [
    (["per capita", "per-capita", "ga per capita", "general assembly assessment",
      "synod per capita", "presbytery per capita"],
     "DENOMINATIONAL_ASSESSMENT", "8700"),
    (["board of pensions", "bop invoice", "bop contribution", "pcusa pension"],
     "BENEFITS", "5210"),
    (["one great hour", "pentecost offering", "peace & global witness", "christmas joy",
      "presbyterian disaster"],
     "MISSIONS", "2710"),
    (["session designated", "terms of call", "toc"],
     "UNKNOWN", None),
]

_DENOM_MAP = {
    DenominationType.UMC: _UMC_OVERRIDES,
    DenominationType.EPISCOPAL: _EPISCOPAL_OVERRIDES,
    DenominationType.CATHOLIC_PARISH: _CATHOLIC_OVERRIDES,
    DenominationType.BAPTIST_INDEPENDENT: _BAPTIST_OVERRIDES,
    DenominationType.PRESBYTERIAN_PCUSA: _PRESBYTERIAN_OVERRIDES,
}


def apply_denomination_rules(
    classified: List[ClassifiedLineItem],
    ctx: AccountingContext,
) -> List[ClassifiedLineItem]:
    """Apply denomination-specific keyword overrides to classified line items."""
    denom = DenominationType(ctx.denomination_type)
    overrides = _DENOM_MAP.get(denom)
    if not overrides:
        return classified

    skill_name = f"denomination_{denom.value.lower()}"
    registry = get_registry()
    denom_skill_loaded = registry.get(skill_name) is not None

    result: List[ClassifiedLineItem] = []
    for item in classified:
        desc_lower = item.description.lower()
        matched = False
        for keywords, new_category, account_hint in overrides:
            if any(kw in desc_lower for kw in keywords):
                # Clone with overridden category
                updated = item.model_copy(deep=True)
                updated.expense_category = new_category
                updated.classification_rationale = (
                    f"[{denom.value} denomination rule] {item.classification_rationale}"
                    + (f" → GL hint: {account_hint}" if account_hint else "")
                )
                if account_hint:
                    updated.flags = item.flags.model_copy(deep=True)
                result.append(updated)
                matched = True
                break
        if not matched:
            result.append(item)

    return result
