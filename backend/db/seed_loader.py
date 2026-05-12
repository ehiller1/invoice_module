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


# ──────────────────────────────────────────────────────────────────────────
# Pledges (separate from AccountingContext)
#
# Pledges aren't part of the church's chart of accounts; they're domain
# events. This helper pulls the `pledges:` list from a seed YAML and runs
# them through the canonical create_pledge() entry point so demo churches
# ship with realistic data instead of empty queues.
# ──────────────────────────────────────────────────────────────────────────

async def seed_pledges_from_yaml(filename: str) -> list[dict]:
    """Create pledges defined in a seed YAML's `pledges:` section.

    Idempotent — if a pledge with the same pledge_id already exists, it
    will be skipped. Returns the list of created pledge records.
    """
    seed_path = SEEDS_DIR / filename
    if not seed_path.exists():
        return []
    with open(seed_path, "r") as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("pledges") or []
    if not raw:
        return []

    from ..membrane.pledge.pledge_matching import create_pledge
    from ..cards.store import get_card_store

    store = get_card_store()
    created: list[dict] = []
    for p in raw:
        pid = p.get("pledge_id")
        if not pid:
            continue
        # Skip if already seeded.
        try:
            existing = store.read(f"pledge-{pid}")
            if existing:
                continue
        except Exception:
            pass
        try:
            rec = await create_pledge(
                pledge_id=pid,
                donor_name=str(p.get("donor_name", "")),
                amount=Decimal(str(p.get("amount", 0))),
                purpose=str(p.get("purpose", "")),
                pledge_date=str(p.get("pledge_date", "")),
                expected_receipt_date=(
                    str(p["expected_receipt_date"]) if p.get("expected_receipt_date") else None
                ),
                restrictions=p.get("restrictions"),
            )
            created.append(rec)
        except Exception:
            # Best-effort — never fail startup on a single bad pledge row.
            continue
    return created


def _load_yaml(filename: str) -> dict:
    p = SEEDS_DIR / filename
    if not p.exists():
        return {}
    with open(p, "r") as f:
        return yaml.safe_load(f) or {}


def seed_fund_balances_from_yaml(church_id: str, filename: str) -> int:
    """Backfill funds.opening_balance from the YAML's funds[].current_balance.

    The standard seed path goes via AccountingContext → save_accounting_context,
    but the funds SQL table doesn't carry a balance column. This helper adds
    the column (idempotent) and writes the seeded values so the dashboard
    financial-position card has something real to show on first run.
    """
    data = _load_yaml(filename)
    funds = data.get("funds") or []
    if not funds:
        return 0
    try:
        from .connection import execute_query
        try:
            execute_query(
                "ALTER TABLE funds ADD COLUMN IF NOT EXISTS opening_balance NUMERIC(14, 2) DEFAULT 0"
            )
        except Exception:
            pass

        row = execute_query(
            "SELECT id FROM churches WHERE church_id = %s", (church_id,), fetch_one=True
        )
        if not row:
            return 0
        church_pk = row.get("id") if isinstance(row, dict) else row[0]

        updated = 0
        for f in funds:
            fid = f.get("fund_id")
            bal = f.get("current_balance")
            if not fid or bal is None:
                continue
            try:
                bal_f = float(bal)
            except (TypeError, ValueError):
                continue
            execute_query(
                "UPDATE funds SET opening_balance = %s WHERE church_id = %s AND fund_id = %s",
                (bal_f, church_pk, fid),
            )
            updated += 1
        return updated
    except Exception:
        return 0


def seed_policies_from_yaml(church_id: str, filename: str) -> list[str]:
    """Create SQL policy_cards from a YAML `policies:` list. Idempotent."""
    from . import card_store
    data = _load_yaml(filename)
    rows = data.get("policies") or []
    if not rows:
        return []
    try:
        existing, _ = card_store.list_policy_cards(church_id, limit=500)
        seen_pids = {(c.get("policy_id") or "") for c in existing if c.get("policy_id")}
    except Exception:
        seen_pids = set()
    created: list[str] = []
    for p in rows:
        pid = p.get("policy_id")
        if not pid or pid in seen_pids:
            continue
        try:
            cid = card_store.create_policy_card(
                church_id=church_id,
                policy_id=pid,
                title=str(p.get("title", "")),
                description=str(p.get("description", "")),
                proposed_by=p.get("proposed_by"),
                requires_vote=bool(p.get("requires_vote", True)),
            )
            created.append(cid)
        except Exception:
            continue
    return created


def seed_recommendations_from_yaml(church_id: str, filename: str) -> list[str]:
    """Create SQL recommendation_cards from a YAML `recommendations:` list. Idempotent on title."""
    from . import card_store
    data = _load_yaml(filename)
    rows = data.get("recommendations") or []
    if not rows:
        return []
    try:
        existing, _ = card_store.list_recommendation_cards(church_id, limit=500)
        seen_titles = {(c.get("title") or "") for c in existing}
    except Exception:
        seen_titles = set()
    created: list[str] = []
    for r in rows:
        title = str(r.get("title", "")).strip()
        if not title or title in seen_titles:
            continue
        try:
            cid = card_store.create_recommendation_card(
                church_id=church_id,
                recommendation_type=str(r.get("recommendation_type", "general")),
                title=title,
                description=str(r.get("description", "")),
                impact_score=float(r.get("impact_score", 0.5)),
                confidence_pct=float(r.get("confidence_pct", 0.8)),
            )
            created.append(cid)
        except Exception:
            continue
    return created


def seed_exceptions_from_yaml(church_id: str, filename: str) -> list[str]:
    """Create SQL exception_cards from a YAML `exceptions:` list. Idempotent on title."""
    from . import card_store
    data = _load_yaml(filename)
    rows = data.get("exceptions") or []
    if not rows:
        return []
    try:
        existing, _ = card_store.list_exception_cards(church_id, limit=500)
        seen_titles = {(c.get("title") or "") for c in existing}
    except Exception:
        seen_titles = set()
    created: list[str] = []
    for e in rows:
        title = str(e.get("title", "")).strip()
        if not title or title in seen_titles:
            continue
        try:
            cid = card_store.create_exception_card(
                church_id=church_id,
                exception_type=str(e.get("exception_type", "general")),
                title=title,
                description=str(e.get("description", "")),
                evidence=e.get("evidence"),
                suggested_action=e.get("suggested_action"),
            )
            created.append(cid)
        except Exception:
            continue
    return created


async def seed_accruals_from_yaml(filename: str) -> list[dict]:
    """Create accrual schedules from a YAML `accruals:` list. Idempotent on description hash."""
    import uuid
    data = _load_yaml(filename)
    rows = data.get("accruals") or []
    if not rows:
        return []

    from ..membrane.accrual.accrual import create_accrual_schedule
    from ..cards.store import get_card_store

    store = get_card_store()
    # Use description as a stable identity key (no UUID until create).
    try:
        existing_cards = store.query_by_principal("accrual-engine") if hasattr(store, "query_by_principal") else []
        seen_descs = {(c.get("metadata", {}) or {}).get("description") for c in existing_cards}
    except Exception:
        seen_descs = set()

    created: list[dict] = []
    for a in rows:
        desc = str(a.get("description", "")).strip()
        if not desc or desc in seen_descs:
            continue
        try:
            rec = await create_accrual_schedule(
                schedule_id=f"sched-{uuid.uuid4().hex[:8]}",
                description=desc,
                total_amount=Decimal(str(a.get("total_amount", "0"))),
                period_count=int(a.get("period_count", 1)),
                period_type=str(a.get("period_type", "monthly")),
                start_date=str(a.get("start_date", "")),
                expense_account=str(a.get("expense_account", "")),
            )
            created.append(rec)
        except Exception:
            continue
    return created
