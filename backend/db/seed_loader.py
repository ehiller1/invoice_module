"""Load church AccountingContext from YAML seed files.

Decouples church template data from Python source code.
All church configuration is now in backend/db/seeds/*.yaml files.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from ..models.schemas import (
    Account,
    AccountingContext,
    ApportionmentAccount,
    DenominationType,
    Fund,
    FundCategory,
    RestrictionClass,
)


SEEDS_DIR = Path(__file__).resolve().parent / "seeds"


def load_seed_yaml(filename: str) -> AccountingContext:
    """Load church accounting context from a YAML file.

    Args:
        filename: Basename of YAML file in seeds/ directory (e.g., 'grace_umc.yaml')

    Returns:
        AccountingContext object ready to persist

    Raises:
        FileNotFoundError: If YAML file doesn't exist
        ValueError: If YAML structure is invalid
    """
    seed_path = SEEDS_DIR / filename
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_path}")

    with open(seed_path, "r") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML structure in {filename}: expected dict, got {type(data)}")

    return _build_accounting_context(data)


def _build_accounting_context(data: dict) -> AccountingContext:
    """Build AccountingContext from YAML-loaded dict."""
    # Parse basic church info
    church_id = data.get("church_id")
    if not church_id or not isinstance(church_id, str):
        raise ValueError("church_id is required and must be a string")

    church_name = data.get("church_name", church_id)
    if not isinstance(church_name, str):
        church_name = str(church_name)

    denomination_str = data.get("denomination_type", "OTHER")
    fiscal_year = int(data.get("fiscal_year", 2026))

    # Parse fiscal year start date
    fiscal_year_start_str = data.get("fiscal_year_start", f"{fiscal_year}-01-01")
    fiscal_year_start = _parse_date(fiscal_year_start_str)

    # Parse denomination type
    try:
        denomination_type = DenominationType(denomination_str)
    except (ValueError, KeyError):
        denomination_type = DenominationType.OTHER

    # Build funds
    funds: list[Fund] = []
    for fund_data in data.get("funds", []):
        try:
            fund_category = FundCategory(fund_data.get("fund_category", "GENERAL_OPERATING"))
        except (ValueError, KeyError):
            fund_category = FundCategory.GENERAL_OPERATING

        try:
            restriction_class = RestrictionClass(fund_data.get("restriction_class", "WITHOUT_RESTRICTION"))
        except (ValueError, KeyError):
            restriction_class = RestrictionClass.WITHOUT_RESTRICTION

        fund = Fund(
            fund_id=fund_data.get("fund_id"),
            fund_name=fund_data.get("fund_name"),
            fund_category=fund_category,
            restriction_class=restriction_class,
            purpose_description=fund_data.get("purpose_description", ""),
            expenditure_rules=fund_data.get("expenditure_rules", ""),
            current_balance=Decimal(str(fund_data.get("current_balance", "0"))),
        )
        funds.append(fund)

    # Build accounts
    accounts: list[Account] = []
    for acct_data in data.get("accounts", []):
        acct_type = acct_data.get("account_type", "Asset")
        if not isinstance(acct_type, str):
            acct_type = str(acct_type)

        try:
            restriction_class = RestrictionClass(acct_data.get("restriction_class", "WITHOUT_RESTRICTION"))
        except (ValueError, KeyError):
            restriction_class = RestrictionClass.WITHOUT_RESTRICTION

        account = Account(
            account_number=acct_data.get("account_number"),
            account_name=acct_data.get("account_name"),
            account_type=acct_type,
            fund_id=acct_data.get("fund_id", "GEN"),
            restriction_class=restriction_class,
        )
        accounts.append(account)

    # Build apportionment accounts
    apportionment_accounts: list[ApportionmentAccount] = []
    for app_data in data.get("apportionment_accounts", []):
        apportionment = ApportionmentAccount(
            account_number=app_data.get("account_number"),
            pct_of_revenue=Decimal(str(app_data.get("pct_of_revenue", "0"))),
        )
        apportionment_accounts.append(apportionment)

    # Build accounting context
    ctx = AccountingContext(
        church_id=church_id,
        church_name=church_name,
        denomination_type=denomination_type,
        fiscal_year=fiscal_year,
        fiscal_year_start=fiscal_year_start,
        accounts=accounts,
        funds=funds,
        apportionment_accounts=apportionment_accounts,
        capitalisation_threshold_usd=Decimal(str(data.get("capitalisation_threshold_usd", "2500"))),
        parsonage_allowance_current_year=Decimal(str(data.get("parsonage_allowance_current_year", "0"))),
        parsonage_allowance_used_ytd=Decimal(str(data.get("parsonage_allowance_used_ytd", "0"))),
    )

    return ctx


def _parse_date(date_str: str) -> date:
    """Parse date from string format YYYY-MM-DD."""
    if isinstance(date_str, date):
        return date_str
    parts = date_str.split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid date format: {date_str}")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def list_available_seeds() -> list[str]:
    """List all available seed files (without .yaml extension)."""
    seeds = []
    for yaml_file in SEEDS_DIR.glob("*.yaml"):
        seeds.append(yaml_file.stem)
    return sorted(seeds)
