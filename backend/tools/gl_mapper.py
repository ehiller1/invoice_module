"""GL account mapper - implements the gl_account_mapper skill workflow."""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from . import coa_store
from ..models import (
    AccountingContext, ClassifiedLineItem, DraftLineAllocation,
    DraftAllocations, InvoiceDocument, Posting, RestrictionClass,
)


CENTS = Decimal("0.01")
AP_ACCOUNT = "2010"  # Accounts Payable


def _find_account(ctx: AccountingContext, account_number: str) -> Optional[Dict]:
    for a in ctx.accounts:
        if a.account_number == account_number:
            return {"account_number": a.account_number, "account_name": a.account_name,
                    "fund_id": a.fund_id, "restriction_class": a.restriction_class}
    return None


def _ap_account_info(ctx: AccountingContext) -> Dict:
    a = _find_account(ctx, AP_ACCOUNT)
    if a:
        return a
    return {"account_number": AP_ACCOUNT, "account_name": "Accounts Payable",
            "fund_id": "GEN", "restriction_class": RestrictionClass.WITHOUT_RESTRICTION}


def _fund_name(ctx: AccountingContext, fund_id: str) -> str:
    for f in ctx.funds:
        if f.fund_id == fund_id:
            return f.fund_name
    return fund_id


def _best_account_for(church_id: str, category: str, ministry: Optional[str],
                      fund_ids: List[str], capitalise: bool, is_housing: bool,
                      is_missions_pt: bool, is_apportionment: bool) -> tuple[str, str, float, str]:
    """Use semantic search to find best GL account. Returns (account_num, account_name, confidence, rationale)."""
    # Build a rich semantic query
    if capitalise:
        query = f"capital expenditure fixed asset {category}"
    elif is_housing:
        query = "clergy housing parsonage utilities"
    elif is_missions_pt:
        query = "missions pass-through disbursements restricted"
    elif is_apportionment:
        query = "denominational assessment apportionment conference"
    else:
        parts = [category.replace("_", " ").lower()]
        if ministry:
            parts.append(ministry.replace("_", " ").lower())
        query = " ".join(parts)

    results = coa_store.semantic_search(church_id, query, k=5, fund_filter=fund_ids)
    if results:
        top = results[0]
        return (top["account_number"], top["account_name"],
                min(0.99, top["score"]), f"Semantic search top match (score={top['score']:.2f})")

    # Hardcoded fallback ranges per FRS §2.2
    if capitalise:
        return "9200", "Capital Expenditures", 0.90, "Capitalise flag → 9200 range"
    if is_housing:
        return "5101", "Clergy Compensation - Housing Allowance", 0.90, "Housing flag → 5100 range"
    if is_missions_pt:
        return "6600", "Missions - Pass-Through Disbursements", 0.90, "Missions pass-through → 6600"
    if is_apportionment:
        return "8300", "Denominational Apportionment - Conference", 0.90, "Apportionment flag → 8300"
    return "8100", "Office Supplies", 0.55, "Fallback: no semantic match found"


def _build_split_amounts(total: Decimal, allocation_schedule_pcts: List[Dict]) -> List[Decimal]:
    """Split total by percentages summing to 100. Residual goes to largest split."""
    amounts: List[Decimal] = []
    running = Decimal("0")
    for i, split in enumerate(allocation_schedule_pcts):
        pct = Decimal(str(split["pct"])) / Decimal("100")
        if i == len(allocation_schedule_pcts) - 1:
            amounts.append((total - running).quantize(CENTS))
        else:
            amt = (total * pct).quantize(CENTS, rounding=ROUND_HALF_UP)
            amounts.append(amt)
            running += amt
    return amounts


def map_line_items(
    invoice: InvoiceDocument,
    classified: List[ClassifiedLineItem],
    ctx: AccountingContext,
    allocation_override: Optional[Dict[str, List[Dict]]] = None,
) -> DraftAllocations:
    """Implements gl_account_mapper skill steps 1-11."""
    ap_info = _ap_account_info(ctx)
    override = allocation_override or {}

    lines: List[DraftLineAllocation] = []
    total_doc_debit = Decimal("0")
    total_doc_credit = Decimal("0")

    for item in classified:
        postings: List[Posting] = []

        # Step 1: allocation_override takes precedence
        if item.line_id in override:
            for o in override[item.line_id]:
                postings.append(Posting(**o))
        else:
            flags = item.flags
            eligible = item.fund_eligibility or ["GEN"]

            # Determine the schedule if split required
            schedule_splits: Optional[List[Dict]] = None
            if flags.is_split_required and not flags.requires_hitl:
                for sched in ctx.allocation_schedules:
                    if item.expense_category in sched.applies_to_categories:
                        schedule_splits = sched.allocations
                        break

            if schedule_splits and len(eligible) > 1:
                amounts = _build_split_amounts(item.amount, schedule_splits)
                for split, amt in zip(schedule_splits, amounts):
                    fund_id = split["fund_id"]
                    acct_num, acct_name, conf, rationale = _best_account_for(
                        ctx.church_id, item.expense_category, item.ministry_area,
                        [fund_id], flags.capitalise, flags.is_housing_related,
                        flags.is_missions_passthrough, flags.is_apportionment,
                    )
                    fn = _find_account(ctx, acct_num)
                    rc = fn["restriction_class"] if fn else RestrictionClass.WITHOUT_RESTRICTION
                    postings.append(Posting(
                        account_number=acct_num, account_name=acct_name,
                        fund_id=fund_id, fund_name=_fund_name(ctx, fund_id),
                        debit_amount=amt, credit_amount=Decimal("0"),
                        restriction_class=rc, confidence=conf,
                        mapping_rationale=f"Allocation schedule split {split['pct']}%. {rationale}",
                    ))
            else:
                # Single fund
                primary_fund = eligible[0]
                acct_num, acct_name, conf, rationale = _best_account_for(
                    ctx.church_id, item.expense_category, item.ministry_area,
                    eligible, flags.capitalise, flags.is_housing_related,
                    flags.is_missions_passthrough, flags.is_apportionment,
                )
                fn = _find_account(ctx, acct_num)
                rc = fn["restriction_class"] if fn else RestrictionClass.WITHOUT_RESTRICTION

                # Capitalise: 9200 range
                if flags.capitalise and not acct_num.startswith("92"):
                    acct_num, acct_name = "9200", "Capital Expenditures"
                    rationale += " [capitalise override to 9200]"

                # Housing: 5100 range
                if flags.is_housing_related and not acct_num.startswith("51"):
                    acct_num, acct_name = "5101", "Clergy Compensation - Housing Allowance"
                    rationale += " [housing override to 5101]"

                postings.append(Posting(
                    account_number=acct_num, account_name=acct_name,
                    fund_id=primary_fund, fund_name=_fund_name(ctx, primary_fund),
                    debit_amount=item.amount, credit_amount=Decimal("0"),
                    restriction_class=rc, confidence=conf,
                    mapping_rationale=rationale,
                ))

        # Credit side: AP for each debit posting
        for p in list(postings):
            if p.debit_amount > 0:
                postings.append(Posting(
                    account_number=ap_info["account_number"],
                    account_name=ap_info["account_name"],
                    fund_id=ap_info["fund_id"],
                    fund_name=_fund_name(ctx, ap_info["fund_id"]),
                    debit_amount=Decimal("0"),
                    credit_amount=p.debit_amount,
                    restriction_class=ap_info["restriction_class"],
                    confidence=1.0,
                    mapping_rationale="Accounts Payable credit (double-entry).",
                ))

        total_deb = sum((p.debit_amount for p in postings), Decimal("0"))
        total_cred = sum((p.credit_amount for p in postings), Decimal("0"))
        balanced = total_deb == total_cred

        lines.append(DraftLineAllocation(
            line_id=item.line_id,
            description=item.description,
            postings=postings,
            total_debits=total_deb,
            total_credits=total_cred,
            balanced=balanced,
        ))
        total_doc_debit += total_deb
        total_doc_credit += total_cred

    doc_balanced = total_doc_debit == total_doc_credit
    return DraftAllocations(
        invoice_number=invoice.invoice_number,
        lines=lines,
        document_total_debits=total_doc_debit,
        document_total_credits=total_doc_credit,
        document_balanced=doc_balanced,
    )
