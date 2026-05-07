"""Year-forward budget projection (FR-03.3).

Projects full-year spend based on the YTD run rate so that an over-budget
trajectory can be flagged before the variance becomes material.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from backend.models.schemas import AccountingContext


@dataclass
class AccountProjection:
    account_number: str
    account_name: str
    annual_budget: Decimal
    ytd_actual: Decimal
    monthly_avg: Decimal
    projected_year_end: Decimal
    projected_overage: Decimal  # negative = under, positive = over
    months_elapsed: int
    months_remaining: int
    will_overspend: bool


@dataclass
class ProjectionReport:
    as_of: date
    fiscal_year: int
    months_elapsed: int
    months_remaining: int
    accounts: List[AccountProjection]
    total_projected_overage: Decimal
    accounts_predicted_to_overspend: int


def _months_elapsed(fiscal_year_start: date, today: date) -> int:
    """Months elapsed in the fiscal year as of `today` (1..12)."""
    if today < fiscal_year_start:
        return 0
    months = (today.year - fiscal_year_start.year) * 12 + (
        today.month - fiscal_year_start.month
    )
    # Count the current month if at least its first-of-month boundary
    # has been crossed.
    if today.day >= fiscal_year_start.day:
        months += 1
    return min(max(months, 1), 12)  # cap at 12


def project_year_end(
    ctx: AccountingContext,
    today: Optional[date] = None,
) -> ProjectionReport:
    """Project end-of-year totals based on YTD run rate.

    Strategy: for each budgeted account, compute monthly_avg = ytd / months_elapsed,
    then projected_year_end = monthly_avg * 12. Overspend flagged when
    projected_year_end > annual_budget.
    """
    today = today or date.today()
    fy_start = ctx.fiscal_year_start
    months_elapsed = _months_elapsed(fy_start, today)
    months_remaining = max(12 - months_elapsed, 0)

    if not ctx.budget:
        return ProjectionReport(
            as_of=today,
            fiscal_year=ctx.fiscal_year,
            months_elapsed=months_elapsed,
            months_remaining=months_remaining,
            accounts=[],
            total_projected_overage=Decimal("0"),
            accounts_predicted_to_overspend=0,
        )

    ytd_actuals = ctx.ytd_actuals or {}
    accounts_by_no = {a.account_number: a for a in ctx.accounts}

    accounts: List[AccountProjection] = []
    total_overage = Decimal("0")
    overspend_count = 0

    for account_number, budget_month in ctx.budget.accounts.items():
        annual = Decimal(str(budget_month.annual_total))
        if annual <= 0:
            continue  # skip unbudgeted accounts

        ytd = Decimal(str(ytd_actuals.get(account_number, Decimal("0"))))
        denom = max(months_elapsed, 1)
        monthly_avg = ytd / Decimal(denom)
        projected = monthly_avg * Decimal(12)
        overage = projected - annual
        will_over = projected > annual

        acct = accounts_by_no.get(account_number)
        account_name = acct.account_name if acct else account_number

        accounts.append(
            AccountProjection(
                account_number=account_number,
                account_name=account_name,
                annual_budget=annual,
                ytd_actual=ytd,
                monthly_avg=monthly_avg.quantize(Decimal("0.01")),
                projected_year_end=projected.quantize(Decimal("0.01")),
                projected_overage=overage.quantize(Decimal("0.01")),
                months_elapsed=months_elapsed,
                months_remaining=months_remaining,
                will_overspend=will_over,
            )
        )

        if will_over:
            total_overage += overage
            overspend_count += 1

    return ProjectionReport(
        as_of=today,
        fiscal_year=ctx.fiscal_year,
        months_elapsed=months_elapsed,
        months_remaining=months_remaining,
        accounts=sorted(accounts, key=lambda a: a.projected_overage, reverse=True),
        total_projected_overage=total_overage.quantize(Decimal("0.01")),
        accounts_predicted_to_overspend=overspend_count,
    )
