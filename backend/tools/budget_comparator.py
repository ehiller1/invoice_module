"""Budget comparator — deterministic check of draft postings against annual budget.

Compares each debit posting against `annual_budget − ytd_actual − this_invoice`.
Pure function; no I/O; no LLM. Returns a list of BudgetCheck records (one per
debit posting) including credit-only postings are skipped.
"""
from __future__ import annotations
from decimal import Decimal
from typing import List

from ..models import (
    AccountingContext,
    BudgetCheck,
    BudgetStatus,
    DraftAllocations,
)


def _fmt_money(d: Decimal) -> str:
    """Format a Decimal as a dollars-and-cents string for human-readable reasons."""
    # Quantize to 2dp for display only
    q = d.quantize(Decimal("0.01"))
    return f"{q:,.2f}"


def _account_name(ctx: AccountingContext, account_number: str) -> str:
    for acct in ctx.accounts:
        if acct.account_number == account_number:
            return acct.account_name
    return account_number


def compare_to_budget(
    draft: DraftAllocations,
    ctx: AccountingContext,
) -> List[BudgetCheck]:
    """Compare each debit posting in `draft` against `ctx.budget` plus `ctx.ytd_actuals`.

    Returns one BudgetCheck per debit posting. If `ctx.budget is None`, returns [].
    Credit-only postings are skipped (do not affect YTD).
    """
    if ctx.budget is None:
        return []

    threshold = float(ctx.budget_warning_threshold or 0.80)
    results: List[BudgetCheck] = []

    for line in draft.lines:
        for posting in line.postings:
            this_invoice = Decimal(posting.debit_amount or Decimal("0"))
            if this_invoice <= Decimal("0"):
                continue  # skip credit-only / zero postings

            account_number = posting.account_number
            account_name = posting.account_name or _account_name(ctx, account_number)

            bm = ctx.budget.accounts.get(account_number)
            ytd_actual = Decimal(ctx.ytd_actuals.get(account_number, Decimal("0")))

            if bm is None:
                # No budget configured for this account — informational only
                results.append(BudgetCheck(
                    line_id=line.line_id,
                    account_number=account_number,
                    account_name=account_name,
                    fund_id=posting.fund_id,
                    annual_budget=Decimal("0"),
                    ytd_actual=ytd_actual,
                    this_invoice=this_invoice,
                    after=ytd_actual + this_invoice,
                    remaining=Decimal("0"),
                    consumed_pct=0.0,
                    status=BudgetStatus.NO_BUDGET,
                    reason=f"No budget configured for account {account_number}",
                ))
                continue

            annual = Decimal(bm.annual_total or Decimal("0"))
            after = ytd_actual + this_invoice
            remaining = annual - after

            # Status determination
            if annual == Decimal("0"):
                # Any positive invoice with zero budget => OVER
                status = BudgetStatus.OVER_BUDGET
                consumed_pct = float("inf") if after > 0 else 0.0
                reason = (
                    f"OVER BUDGET: {account_name} ({account_number}) — "
                    f"no annual budget but ${_fmt_money(this_invoice)} invoiced"
                )
            else:
                consumed_pct = float(after / annual)
                if after > annual:
                    status = BudgetStatus.OVER_BUDGET
                    reason = (
                        f"OVER BUDGET: {account_name} ({account_number}) — "
                        f"projected ${_fmt_money(after)} exceeds annual "
                        f"${_fmt_money(annual)} by ${_fmt_money(after - annual)} "
                        f"({consumed_pct:.0%} consumed)"
                    )
                elif after > Decimal(str(threshold)) * annual:
                    status = BudgetStatus.WARNING
                    reason = (
                        f"WARNING: {account_name} ({account_number}) at "
                        f"{consumed_pct:.0%} of annual budget after this invoice"
                    )
                else:
                    status = BudgetStatus.WITHIN_BUDGET
                    reason = (
                        f"Within budget: {account_name} — "
                        f"${_fmt_money(remaining)} remaining of ${_fmt_money(annual)}"
                    )

            results.append(BudgetCheck(
                line_id=line.line_id,
                account_number=account_number,
                account_name=account_name,
                fund_id=posting.fund_id,
                annual_budget=annual,
                ytd_actual=ytd_actual,
                this_invoice=this_invoice,
                after=after,
                remaining=remaining,
                consumed_pct=consumed_pct if consumed_pct != float("inf") else 999.0,
                status=status,
                reason=reason,
            ))

    return results
