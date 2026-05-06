"""Line item classifier - implements the line_item_classifier skill workflow."""
from __future__ import annotations
from decimal import Decimal
from typing import List, Dict, Optional

from . import coa_store
from ..models import (
    AccountingContext, ClassificationFlags, ClassifiedLineItem,
    InvoiceDocument, LineItem,
)


# Keyword-based taxonomy mirrors expense_taxonomy_v1 SKILL.md.
TAXONOMY: List[Dict] = [
    # Personnel
    {"category": "CLERGY_HOUSING", "keywords": ["parsonage", "manse", "rectory", "vicarage"], "ministry": None,
     "is_housing_related": True},
    {"category": "CLERGY_COMPENSATION", "keywords": ["pastor salary", "clergy stipend", "minister salary"], "ministry": None},
    {"category": "SECA_REIMBURSEMENT", "keywords": ["seca", "self-employment tax"], "ministry": None},
    {"category": "LAY_STAFF_WAGES", "keywords": ["staff wage", "secretary salary", "music director", "nursery staff"], "ministry": None},
    {"category": "BENEFITS", "keywords": ["health insurance", "retirement contribution", "dental", "vision"], "ministry": None},
    # Worship
    {"category": "WORSHIP", "keywords": ["altar flowers", "communion", "sheet music", "hymnal", "choir robes", "sound system", "audio equipment"], "ministry": "WORSHIP"},
    # Children
    {"category": "CHILDREN_MINISTRY", "keywords": ["vbs", "vacation bible school", "sunday school curriculum", "nursery supplies", "children's curriculum"], "ministry": "CHILDREN"},
    # Youth
    {"category": "YOUTH_MINISTRY", "keywords": ["youth retreat", "youth camp", "youth snacks", "youth group", "confirmation"], "ministry": "YOUTH"},
    # Adult Ed
    {"category": "ADULT_EDUCATION", "keywords": ["adult class", "small group materials", "bible study book"], "ministry": "ADULT_EDUCATION"},
    # Missions
    {"category": "MISSIONS", "keywords": ["missionary support", "mission trip", "world relief", "cooperative program", "world missions giving"], "ministry": "MISSIONS",
     "is_missions_passthrough": True},
    # Pastoral care
    {"category": "PASTORAL_CARE", "keywords": ["hospital visit", "bereavement", "pastoral counseling"], "ministry": "PASTORAL_CARE"},
    # Facility
    {"category": "MORTGAGE_RENT", "keywords": ["mortgage", "lease payment", "rent due"], "ministry": "FACILITIES"},
    {"category": "UTILITIES", "keywords": ["electric", "electricity", "kwh", "natural gas", "gas service", "water", "sewer", "trash", "internet", "phone bill", "telephone"], "ministry": "FACILITIES"},
    {"category": "MAINTENANCE_REPAIRS", "keywords": ["hvac", "air conditioning", "plumbing", "roof repair", "painting", "boiler"], "ministry": "FACILITIES"},
    {"category": "JANITORIAL", "keywords": ["janitorial", "cleaning service", "custodial"], "ministry": "FACILITIES"},
    {"category": "LANDSCAPING", "keywords": ["lawn", "landscaping", "grounds", "snow removal"], "ministry": "FACILITIES"},
    {"category": "INSURANCE", "keywords": ["liability insurance", "property insurance", "workers comp", "d&o insurance"], "ministry": "ADMINISTRATION"},
    {"category": "TECHNOLOGY", "keywords": ["software", "subscription", "saas", "computer", "server", "av equipment", "projector"], "ministry": "ADMINISTRATION"},
    # Admin
    {"category": "OFFICE_SUPPLIES", "keywords": ["office supplies", "paper", "toner", "envelopes", "postage", "printer ink"], "ministry": "ADMINISTRATION"},
    {"category": "LEGAL_AUDIT", "keywords": ["attorney", "legal fees", "audit fee", "cpa fee"], "ministry": "ADMINISTRATION"},
    {"category": "DENOMINATIONAL_ASSESSMENT", "keywords": ["diocesan assessment", "conference apportionment", "district apportionment", "presbytery", "synod assessment", "general council on finance"], "ministry": "ADMINISTRATION",
     "is_apportionment": True},
    {"category": "STEWARDSHIP_FUNDRAISING", "keywords": ["pledge cards", "capital campaign brochure", "stewardship materials"], "ministry": "ADMINISTRATION"},
    # Capital
    {"category": "EQUIPMENT", "keywords": ["copier", "vehicle purchase", "appliance"], "ministry": "FACILITIES"},
    {"category": "IMPROVEMENT", "keywords": ["parking lot", "remodel", "renovation", "addition"], "ministry": "FACILITIES"},
    {"category": "LOAN_PRINCIPAL", "keywords": ["loan principal", "principal payment"], "ministry": None},
    # Special
    {"category": "BENEVOLENCE", "keywords": ["benevolence", "emergency aid", "rent assistance"], "ministry": None},
]


# Vendor lists (in production these come from vendor_history_db_tool / IRS API per FRS §9.14)
PARSONAGE_VENDORS = {"city utilities district", "parsonage repairs llc", "manse maintenance"}
MISSIONARY_ORGS = {"world missions board", "wycliffe bible translators", "samaritans purse",
                   "compassion international", "international mission board"}
DENOMINATIONAL_BODIES = {"united methodist conference", "umc conference", "diocese of",
                         "presbytery of", "synod of", "southern baptist convention"}


def _score_category(description: str) -> tuple[str, float, Optional[str], Dict[str, bool]]:
    desc = description.lower()
    best_score = 0.0
    best_cat = "UNKNOWN"
    best_ministry: Optional[str] = None
    best_flags: Dict[str, bool] = {}
    for entry in TAXONOMY:
        for kw in entry["keywords"]:
            if kw in desc:
                score = min(1.0, 0.65 + 0.05 * len(kw.split()))
                if score > best_score:
                    best_score = score
                    best_cat = entry["category"]
                    best_ministry = entry.get("ministry")
                    best_flags = {k: v for k, v in entry.items()
                                  if k.startswith("is_") or k == "capitalise"}
    if best_score == 0.0:
        best_score = 0.45  # below 0.80 → triggers HITL
    return best_cat, best_score, best_ministry, best_flags


def _vendor_in(vendor: str, registry: set) -> bool:
    v = vendor.lower()
    return any(name in v for name in registry)


def _eligible_funds(category: str, ministry: Optional[str], ctx: AccountingContext,
                    flags: Dict[str, bool]) -> List[str]:
    """Intersect candidate funds based on restriction class and purpose match."""
    fund_ids: List[str] = []
    for f in ctx.funds:
        # General operating is always eligible for non-restricted expense categories
        if f.fund_id == "GEN" and not flags.get("is_missions_passthrough"):
            fund_ids.append(f.fund_id)
            continue
        # Building / capital fund for capital items
        if flags.get("capitalise") and f.fund_category.value == "CAPITAL_CAMPAIGN":
            fund_ids.append(f.fund_id)
            continue
        # Missions fund for missions pass-through
        if flags.get("is_missions_passthrough") and "miss" in f.fund_id.lower():
            fund_ids.append(f.fund_id)
            continue
        # Youth fund for youth ministry
        if ministry == "YOUTH" and "youth" in f.fund_name.lower():
            fund_ids.append(f.fund_id)
            continue
        # Benevolence fund for benevolence
        if category == "BENEVOLENCE" and "benev" in f.fund_id.lower():
            fund_ids.append(f.fund_id)
            continue
    return fund_ids or ["GEN"]


def classify_line_items(invoice: InvoiceDocument, ctx: AccountingContext,
                        vendor_history: Optional[List[Dict]] = None
                        ) -> List[ClassifiedLineItem]:
    """Implements line_item_classifier SKILL workflow."""
    history_prior = (vendor_history or [])
    has_history = len(history_prior) > 0
    out: List[ClassifiedLineItem] = []
    for li in invoice.line_items:
        category, score, ministry, kw_flags = _score_category(li.description)

        # Vendor history boost (FR-03.5)
        if has_history and category == "UNKNOWN":
            top = history_prior[0]
            category = top.get("expense_category", "UNKNOWN")
            score = min(1.0, score + 0.15)

        # Build flags
        flags = ClassificationFlags(
            is_housing_related=bool(kw_flags.get("is_housing_related"))
                              or _vendor_in(invoice.vendor_name, PARSONAGE_VENDORS),
            is_missions_passthrough=bool(kw_flags.get("is_missions_passthrough"))
                                    and _vendor_in(invoice.vendor_name, MISSIONARY_ORGS),
            capitalise=bool(li.amount > ctx.capitalisation_threshold_usd
                            and category in ("EQUIPMENT", "IMPROVEMENT", "TECHNOLOGY")),
            is_apportionment=bool(kw_flags.get("is_apportionment"))
                             and _vendor_in(invoice.vendor_name, DENOMINATIONAL_BODIES),
            is_split_required=False,
            requires_hitl=False,
        )

        # Apply HITL gates per FRS §4.3
        if score < 0.80:
            flags.requires_hitl = True
        if flags.is_missions_passthrough:
            flags.requires_hitl = True

        # Housing budget validation
        rationale_extras: List[str] = []
        if flags.is_housing_related:
            remaining = ctx.parsonage_allowance_current_year - ctx.parsonage_allowance_used_ytd
            if li.amount > remaining:
                flags.requires_hitl = True
                rationale_extras.append(
                    f"Housing exceeds remaining annual allowance (${remaining})."
                )

        eligible_funds = _eligible_funds(category, ministry, ctx, kw_flags)
        if len(eligible_funds) > 1:
            flags.is_split_required = True
            # Check for an allocation schedule
            has_schedule = any(category in s.applies_to_categories
                               for s in ctx.allocation_schedules)
            if not has_schedule:
                flags.requires_hitl = True
                rationale_extras.append(
                    f"Multiple eligible funds {eligible_funds} and no allocation schedule."
                )

        rationale_parts = [f"Matched category {category} (confidence {score:.2f})."]
        if ministry:
            rationale_parts.append(f"Ministry area: {ministry}.")
        if flags.is_housing_related:
            rationale_parts.append("Vendor or description matches parsonage/housing pattern.")
        if flags.is_missions_passthrough:
            rationale_parts.append("Registered missionary organization → pass-through disbursement.")
        if flags.capitalise:
            rationale_parts.append(
                f"Amount ${li.amount} exceeds capitalisation threshold "
                f"${ctx.capitalisation_threshold_usd}; classify as fixed asset."
            )
        if flags.is_apportionment:
            rationale_parts.append("Denominational body invoice → apportionment account.")
        rationale_parts.extend(rationale_extras)

        out.append(ClassifiedLineItem(
            line_id=li.line_id,
            description=li.description,
            amount=li.amount,
            expense_category=category,
            ministry_area=ministry,
            fund_eligibility=eligible_funds,
            flags=flags,
            classification_rationale=" ".join(rationale_parts),
            confidence=score,
        ))
    return out
