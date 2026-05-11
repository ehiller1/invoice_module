"""COA (Chart of Accounts) persistence — PostgreSQL backend.

Replaces the JSON+ChromaDB-only `backend/tools/coa_store.py` with a
relational persistence layer. The full `AccountingContext` (church header,
GL accounts, funds, budget plan + monthly buckets, YTD actuals) is
shredded across the relational schema and reconstructed on read.

Schema reference:
- churches               (id PK, church_id, name, denomination_type)
- accounting_contexts    (id PK, church_id FK, fiscal_year)
- gl_accounts            (id PK, church_id FK, account_number, account_type, name, is_active)
- funds                  (id PK, church_id FK, fund_id, name, category, is_active)
- budget_plans           (id PK, accounting_context_id FK)
- budget_months          (id PK, budget_plan_id FK, account_number, month, budgeted_amount)
- ytd_actuals            (id PK, church_id FK, account_number, fiscal_year, amount, version)

Optimistic locking on `ytd_actuals.version` is exposed by
`update_ytd_actual()`.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .connection import execute_query
from .transactions import atomic_transaction
from ..events.emitter import emit_event_in_txn
from ..events.schemas import EventType, FinancialEvent, TagKind

from ..models.schemas import (
    Account,
    AccountingContext,
    BudgetMonth,
    BudgetPlan,
    DenominationType,
    Fund,
    FundCategory,
    RestrictionClass,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MONTH_ATTRS = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
)


def _resolve_church_pk(church_id: str) -> int:
    """Resolve string church_id → SERIAL PK. Raise if missing."""
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _try_resolve_church_pk(church_id: str) -> Optional[int]:
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    return int(row["id"]) if row else None


def _ensure_church_row(
    cur,
    church_id: str,
    church_name: str,
    denomination_type: Any,
) -> int:
    """Insert or update a churches row; return its SERIAL id."""
    denom = (
        denomination_type.value
        if hasattr(denomination_type, "value")
        else str(denomination_type)
    )
    cur.execute(
        """
        INSERT INTO churches (church_id, name, denomination_type, updated_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (church_id) DO UPDATE SET
            name = EXCLUDED.name,
            denomination_type = EXCLUDED.denomination_type,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (church_id, church_name, denom),
    )
    return int(cur.fetchone()[0])


def _ensure_accounting_context_row(cur, church_pk: int, fiscal_year: int) -> int:
    cur.execute(
        """
        INSERT INTO accounting_contexts (church_id, fiscal_year, updated_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (church_id, fiscal_year) DO UPDATE SET
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (church_pk, fiscal_year),
    )
    return int(cur.fetchone()[0])


def _decimal(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _restriction_for_account(fund: Optional[Fund]) -> RestrictionClass:
    if fund is None:
        return RestrictionClass.WITHOUT_RESTRICTION
    return fund.restriction_class


# ---------------------------------------------------------------------------
# Public: load / save full AccountingContext
# ---------------------------------------------------------------------------

def load_accounting_context(church_id: str) -> AccountingContext:
    """Load the full AccountingContext for a church.

    Reconstructs accounts, funds, budget plan + months, and YTD actuals from
    the relational schema. Raises ValueError if the church does not exist.
    """
    church_row = execute_query(
        """
        SELECT id, church_id, name, denomination_type
        FROM churches
        WHERE church_id = %s
        """,
        (church_id,),
        fetch_one=True,
    )
    if church_row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    church_pk = int(church_row["id"])

    # Accounting context (most-recent fiscal_year wins if multiple).
    ctx_row = execute_query(
        """
        SELECT id, fiscal_year
        FROM accounting_contexts
        WHERE church_id = %s
        ORDER BY fiscal_year DESC
        LIMIT 1
        """,
        (church_pk,),
        fetch_one=True,
    )
    fiscal_year = int(ctx_row["fiscal_year"]) if ctx_row else datetime.utcnow().year
    accounting_context_pk = int(ctx_row["id"]) if ctx_row else None

    # Funds (load before accounts so we can resolve restriction_class).
    fund_rows = execute_query(
        """
        SELECT fund_id, name, category, is_active
        FROM funds
        WHERE church_id = %s
        ORDER BY fund_id
        """,
        (church_pk,),
    ) or []

    funds: List[Fund] = []
    fund_lookup: Dict[str, Fund] = {}
    for r in fund_rows:
        try:
            category = FundCategory(r.get("category")) if r.get("category") else FundCategory.GENERAL_OPERATING
        except ValueError:
            category = FundCategory.GENERAL_OPERATING
        # Map category → restriction_class with conservative defaults.
        if category in (FundCategory.PERMANENTLY_RESTRICTED,):
            restriction = RestrictionClass.WITH_RESTRICTION_PERMANENT
        elif category in (
            FundCategory.TEMP_RESTRICTED_PURPOSE,
            FundCategory.CAPITAL_CAMPAIGN,
            FundCategory.BOARD_DESIGNATED,
        ):
            restriction = RestrictionClass.WITH_RESTRICTION_PURPOSE
        else:
            restriction = RestrictionClass.WITHOUT_RESTRICTION
        f = Fund(
            fund_id=r["fund_id"],
            fund_name=r.get("name") or r["fund_id"],
            restriction_class=restriction,
            fund_category=category,
        )
        funds.append(f)
        fund_lookup[f.fund_id] = f

    # GL accounts.
    acct_rows = execute_query(
        """
        SELECT account_number, account_type, name, is_active
        FROM gl_accounts
        WHERE church_id = %s
        ORDER BY account_number
        """,
        (church_pk,),
    ) or []

    accounts: List[Account] = []
    # Default fund: first fund or "GEN"
    default_fund_id = funds[0].fund_id if funds else "GEN"
    for r in acct_rows:
        # Note: schema does not store fund_id per account; assign default.
        # Real systems carry fund_id on the account; if not present, use default.
        fund_id = default_fund_id
        accounts.append(
            Account(
                account_number=r["account_number"],
                account_name=r.get("name") or r["account_number"],
                account_type=r.get("account_type") or "Expense",
                fund_id=fund_id,
                restriction_class=_restriction_for_account(fund_lookup.get(fund_id)),
                active=bool(r.get("is_active", True)),
            )
        )

    # Budget plan (most-recent for the accounting context).
    budget: Optional[BudgetPlan] = None
    if accounting_context_pk is not None:
        bp_row = execute_query(
            """
            SELECT id, created_at
            FROM budget_plans
            WHERE accounting_context_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (accounting_context_pk,),
            fetch_one=True,
        )
        if bp_row:
            bp_pk = int(bp_row["id"])
            month_rows = execute_query(
                """
                SELECT account_number, month, budgeted_amount
                FROM budget_months
                WHERE budget_plan_id = %s
                """,
                (bp_pk,),
            ) or []
            buckets: Dict[str, BudgetMonth] = {}
            for mr in month_rows:
                acct = mr["account_number"]
                m = int(mr["month"])
                amt = _decimal(mr.get("budgeted_amount"))
                if acct not in buckets:
                    buckets[acct] = BudgetMonth()
                if 1 <= m <= 12:
                    setattr(buckets[acct], _MONTH_ATTRS[m - 1], amt)
            # Compute annual totals.
            for bm in buckets.values():
                bm.annual_total = sum(
                    (getattr(bm, a) for a in _MONTH_ATTRS),
                    Decimal("0"),
                )
            budget = BudgetPlan(
                fiscal_year=fiscal_year,
                plan_date=date.today(),
                amendment_number=0,
                accounts=buckets,
                uploaded_at=bp_row["created_at"] if bp_row.get("created_at") else datetime.utcnow(),
            )

    # YTD actuals.
    ytd_rows = execute_query(
        """
        SELECT account_number, amount
        FROM ytd_actuals
        WHERE church_id = %s AND fiscal_year = %s
        """,
        (church_pk, fiscal_year),
    ) or []
    ytd_actuals: Dict[str, Decimal] = {
        r["account_number"]: _decimal(r.get("amount")) for r in ytd_rows
    }

    # Denomination type.
    try:
        denom = DenominationType(church_row.get("denomination_type") or "OTHER")
    except ValueError:
        denom = DenominationType.OTHER

    return AccountingContext(
        church_id=church_row["church_id"],
        church_name=church_row.get("name") or church_row["church_id"],
        denomination_type=denom,
        fiscal_year=fiscal_year,
        fiscal_year_start=date(fiscal_year, 1, 1),
        accounts=accounts,
        funds=funds,
        budget=budget,
        ytd_actuals=ytd_actuals,
    )


def save_accounting_context(ctx: AccountingContext) -> None:
    """Persist an entire AccountingContext atomically.

    Upserts the church row, accounting_context, funds, gl_accounts,
    budget_plan + budget_months, and ytd_actuals. Funds and GL accounts
    that disappear from the in-memory ctx are deactivated (not deleted)
    to preserve referential integrity.
    """
    with atomic_transaction() as conn:
        cur = conn.cursor()

        church_pk = _ensure_church_row(
            cur, ctx.church_id, ctx.church_name, ctx.denomination_type
        )
        ac_pk = _ensure_accounting_context_row(cur, church_pk, ctx.fiscal_year)

        # ----- Funds: upsert -----
        seen_fund_ids: List[str] = []
        for fund in ctx.funds:
            cur.execute(
                """
                INSERT INTO funds (church_id, fund_id, name, category, is_active, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (church_id, fund_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    is_active = EXCLUDED.is_active,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    church_pk,
                    fund.fund_id,
                    fund.fund_name,
                    fund.fund_category.value
                    if hasattr(fund.fund_category, "value")
                    else str(fund.fund_category),
                    True,
                ),
            )
            seen_fund_ids.append(fund.fund_id)

        # Deactivate funds that no longer exist in the context.
        if seen_fund_ids:
            cur.execute(
                """
                UPDATE funds SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE church_id = %s AND fund_id NOT IN %s
                """,
                (church_pk, tuple(seen_fund_ids)),
            )

        # ----- GL accounts: upsert -----
        seen_account_numbers: List[str] = []
        for acct in ctx.accounts:
            cur.execute(
                """
                INSERT INTO gl_accounts (
                    church_id, account_number, account_type, name, is_active, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (church_id, account_number) DO UPDATE SET
                    account_type = EXCLUDED.account_type,
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    church_pk,
                    acct.account_number,
                    acct.account_type,
                    acct.account_name,
                    bool(acct.active),
                ),
            )
            seen_account_numbers.append(acct.account_number)

        if seen_account_numbers:
            cur.execute(
                """
                UPDATE gl_accounts SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE church_id = %s AND account_number NOT IN %s
                """,
                (church_pk, tuple(seen_account_numbers)),
            )

        # ----- Budget plan + months -----
        if ctx.budget is not None:
            # Replace strategy: delete prior plans for this context, insert fresh.
            cur.execute(
                "DELETE FROM budget_plans WHERE accounting_context_id = %s",
                (ac_pk,),
            )
            cur.execute(
                """
                INSERT INTO budget_plans (accounting_context_id)
                VALUES (%s) RETURNING id
                """,
                (ac_pk,),
            )
            bp_pk = int(cur.fetchone()[0])

            for acct_num, bm in ctx.budget.accounts.items():
                for m_idx, attr in enumerate(_MONTH_ATTRS, start=1):
                    amt = getattr(bm, attr, Decimal("0")) or Decimal("0")
                    if amt == Decimal("0"):
                        # Skip zero rows for compactness.
                        continue
                    cur.execute(
                        """
                        INSERT INTO budget_months (
                            budget_plan_id, account_number, month, budgeted_amount
                        ) VALUES (%s, %s, %s, %s)
                        """,
                        (bp_pk, acct_num, m_idx, amt),
                    )

        # ----- YTD actuals -----
        for acct_num, amount in (ctx.ytd_actuals or {}).items():
            cur.execute(
                """
                INSERT INTO ytd_actuals (
                    church_id, account_number, fiscal_year, amount, version, updated_at
                )
                VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (church_id, account_number, fiscal_year) DO UPDATE SET
                    amount = EXCLUDED.amount,
                    version = ytd_actuals.version + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (church_pk, acct_num, ctx.fiscal_year, _decimal(amount)),
            )

        cur.close()

    # Best-effort: rebuild the ChromaDB semantic index. Optional/async.
    try:
        from ..tools import coa_store as _legacy_kb  # type: ignore
        _legacy_kb._rebuild_index(ctx)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Listings & summaries
# ---------------------------------------------------------------------------

def list_churches() -> List[dict]:
    """Return a summary record per church."""
    rows = execute_query(
        """
        SELECT
            c.church_id,
            c.name,
            c.denomination_type,
            (SELECT COUNT(*) FROM gl_accounts a
                WHERE a.church_id = c.id AND a.is_active) AS account_count,
            (SELECT COUNT(*) FROM funds f
                WHERE f.church_id = c.id AND f.is_active) AS fund_count
        FROM churches c
        ORDER BY c.name
        """,
    ) or []
    return [
        {
            "church_id": r["church_id"],
            "church_name": r.get("name") or r["church_id"],
            "denomination_type": r.get("denomination_type") or "OTHER",
            "account_count": int(r.get("account_count") or 0),
            "fund_count": int(r.get("fund_count") or 0),
        }
        for r in rows
    ]


def find_account_by_name(church_id: str, name_pattern: str, account_type: Optional[str] = None) -> Optional[str]:
    """Find a GL account number by name pattern.

    Args:
        church_id: Church identifier
        name_pattern: Partial name to search for (case-insensitive substring)
        account_type: Optional account type to filter (e.g., "Expense", "Liability")

    Returns:
        Account number if found, None otherwise. If multiple matches, returns first active account.
    """
    church_pk = _try_resolve_church_pk(church_id)
    if church_pk is None:
        return None

    query = """
        SELECT account_number
        FROM gl_accounts
        WHERE church_id = %s
          AND is_active = true
          AND LOWER(name) LIKE LOWER(%s)
    """
    params: list[Any] = [church_pk, f"%{name_pattern}%"]

    if account_type:
        query += " AND account_type = %s"
        params.append(account_type)

    query += " ORDER BY account_number LIMIT 1"

    row = execute_query(query, tuple(params), fetch_one=True)
    return row["account_number"] if row else None


def find_account_by_type(church_id: str, account_type: str) -> Optional[str]:
    """Find first GL account of a given type.

    Useful for finding default accounts (e.g., first Expense account).

    Args:
        church_id: Church identifier
        account_type: Account type (e.g., "Asset", "Liability", "Expense", "Revenue")

    Returns:
        Account number if found, None otherwise.
    """
    church_pk = _try_resolve_church_pk(church_id)
    if church_pk is None:
        return None

    row = execute_query(
        """
        SELECT account_number
        FROM gl_accounts
        WHERE church_id = %s
          AND is_active = true
          AND account_type = %s
        ORDER BY account_number
        LIMIT 1
        """,
        (church_pk, account_type),
        fetch_one=True,
    )
    return row["account_number"] if row else None


# ---------------------------------------------------------------------------
# Single-account / single-fund mutators
# ---------------------------------------------------------------------------

def upsert_account(church_id: str, account: Account) -> None:
    """Insert or update a single GL account."""
    church_pk = _resolve_church_pk(church_id)
    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO gl_accounts (
                church_id, account_number, account_type, name, is_active, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (church_id, account_number) DO UPDATE SET
                account_type = EXCLUDED.account_type,
                name = EXCLUDED.name,
                is_active = EXCLUDED.is_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                church_pk,
                account.account_number,
                account.account_type,
                account.account_name,
                bool(account.active),
            ),
        )
        cur.close()


def delete_account(church_id: str, account_number: str) -> None:
    """Delete a GL account."""
    church_pk = _resolve_church_pk(church_id)
    execute_query(
        "DELETE FROM gl_accounts WHERE church_id = %s AND account_number = %s",
        (church_pk, account_number),
    )


def upsert_fund(church_id: str, fund: Fund) -> None:
    """Insert or update a single fund."""
    church_pk = _resolve_church_pk(church_id)
    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO funds (church_id, fund_id, name, category, is_active, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (church_id, fund_id) DO UPDATE SET
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                is_active = EXCLUDED.is_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                church_pk,
                fund.fund_id,
                fund.fund_name,
                fund.fund_category.value
                if hasattr(fund.fund_category, "value")
                else str(fund.fund_category),
                True,
            ),
        )
        cur.close()


def delete_fund(church_id: str, fund_id: str) -> None:
    """Delete a fund (cascade handled by FK)."""
    church_pk = _resolve_church_pk(church_id)
    execute_query(
        "DELETE FROM funds WHERE church_id = %s AND fund_id = %s",
        (church_pk, fund_id),
    )


# ---------------------------------------------------------------------------
# YTD actuals: optimistic-lock increment
# ---------------------------------------------------------------------------

def update_ytd_actual(
    church_id: str,
    account_number: str,
    fiscal_year: int,
    delta: Decimal,
    max_retries: int = 3,
) -> Decimal:
    """Atomically increment a YTD actual using optimistic locking.

    Algorithm:
      1. SELECT current (amount, version).
      2. UPDATE … SET amount = amount + delta, version = version + 1
         WHERE version = expected_version.
      3. If 0 rows updated, retry up to `max_retries`.
      4. Return the new amount.

    If the row does not exist, it is INSERTed at amount=delta.
    """
    church_pk = _resolve_church_pk(church_id)
    delta_d = _decimal(delta)

    for _ in range(max(1, max_retries)):
        row = execute_query(
            """
            SELECT amount, version FROM ytd_actuals
            WHERE church_id = %s AND account_number = %s AND fiscal_year = %s
            """,
            (church_pk, account_number, fiscal_year),
            fetch_one=True,
        )

        if row is None:
            # Insert; rely on UNIQUE constraint to detect a race.
            try:
                with atomic_transaction() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO ytd_actuals
                            (church_id, account_number, fiscal_year, amount, version, updated_at)
                        VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
                        RETURNING amount
                        """,
                        (church_pk, account_number, fiscal_year, delta_d),
                    )
                    new_amount = _decimal(cur.fetchone()[0])
                    cur.close()
                    # Phase 5a: dual-write YTDAdjusted event.
                    _ev = FinancialEvent(
                        event_type=EventType.YTD_ADJUSTED,
                        church_id=church_id,
                        payload={
                            "account_number": account_number,
                            "fiscal_year": fiscal_year,
                            "delta": str(delta_d),
                            "new_amount": str(new_amount),
                            "op": "INSERT",
                        },
                    )
                    _ev.add_tag(TagKind.ACCOUNT, account_number)
                    _ev.add_tag(TagKind.PERIOD, str(fiscal_year))
                    emit_event_in_txn(conn, _ev)
                return new_amount
            except Exception:
                # Likely a unique-violation race; loop and try the UPDATE path.
                continue

        expected_version = int(row["version"])
        with atomic_transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE ytd_actuals
                   SET amount  = amount + %s,
                       version = version + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE church_id = %s
                   AND account_number = %s
                   AND fiscal_year = %s
                   AND version = %s
                RETURNING amount
                """,
                (
                    delta_d,
                    church_pk,
                    account_number,
                    fiscal_year,
                    expected_version,
                ),
            )
            updated = cur.fetchone()
            cur.close()
            if updated is not None:
                new_amount = _decimal(updated[0])
                # Phase 5a: dual-write YTDAdjusted event.
                _ev = FinancialEvent(
                    event_type=EventType.YTD_ADJUSTED,
                    church_id=church_id,
                    payload={
                        "account_number": account_number,
                        "fiscal_year": fiscal_year,
                        "delta": str(delta_d),
                        "new_amount": str(new_amount),
                        "op": "UPDATE",
                        "version": expected_version + 1,
                    },
                )
                _ev.add_tag(TagKind.ACCOUNT, account_number)
                _ev.add_tag(TagKind.PERIOD, str(fiscal_year))
                emit_event_in_txn(conn, _ev)
                return new_amount
        if updated is not None:
            return _decimal(updated[0])
        # Else: version drifted — retry.

    raise RuntimeError(
        f"update_ytd_actual: optimistic-lock contention exceeded {max_retries} retries "
        f"for church={church_id} account={account_number} fy={fiscal_year}"
    )


def reset_ytd_actuals(church_id: str, fiscal_year: int) -> None:
    """Zero out every YTD actual row for a fiscal year."""
    church_pk = _resolve_church_pk(church_id)
    execute_query(
        """
        UPDATE ytd_actuals
           SET amount = 0,
               version = version + 1,
               updated_at = CURRENT_TIMESTAMP
         WHERE church_id = %s AND fiscal_year = %s
        """,
        (church_pk, fiscal_year),
    )


# ---------------------------------------------------------------------------
# Variance / reporting
# ---------------------------------------------------------------------------

def get_budget_variance(church_id: str, fiscal_year: int) -> Dict[str, Dict[str, Any]]:
    """Return per-account budget-vs-actual variance.

    Output: {account_number: {budgeted: Decimal, actual: Decimal,
                              variance: Decimal, consumed_pct: float,
                              status: str}}
    """
    church_pk = _resolve_church_pk(church_id)

    rows = execute_query(
        """
        WITH bm AS (
            SELECT bm.account_number,
                   SUM(bm.budgeted_amount) AS budgeted
            FROM budget_months bm
            JOIN budget_plans bp ON bp.id = bm.budget_plan_id
            JOIN accounting_contexts ac ON ac.id = bp.accounting_context_id
            WHERE ac.church_id = %s AND ac.fiscal_year = %s
            GROUP BY bm.account_number
        ),
        ya AS (
            SELECT account_number, amount AS actual
            FROM ytd_actuals
            WHERE church_id = %s AND fiscal_year = %s
        )
        SELECT
            COALESCE(bm.account_number, ya.account_number) AS account_number,
            COALESCE(bm.budgeted, 0) AS budgeted,
            COALESCE(ya.actual, 0)   AS actual
        FROM bm FULL OUTER JOIN ya ON bm.account_number = ya.account_number
        ORDER BY account_number
        """,
        (church_pk, fiscal_year, church_pk, fiscal_year),
    ) or []

    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        budgeted = _decimal(r["budgeted"])
        actual = _decimal(r["actual"])
        variance = budgeted - actual  # positive = under budget
        consumed_pct = float(actual / budgeted) if budgeted > 0 else (
            1.0 if actual > 0 else 0.0
        )
        if budgeted == 0:
            status = "NO_BUDGET"
        elif consumed_pct > 1.0:
            status = "OVER_BUDGET"
        elif consumed_pct >= 0.80:
            status = "WARNING"
        else:
            status = "WITHIN_BUDGET"

        out[r["account_number"]] = {
            "budgeted": budgeted,
            "actual": actual,
            "variance": variance,
            "consumed_pct": consumed_pct,
            "status": status,
        }
    return out


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def ensure_seed() -> List[str]:
    """Idempotent seed for first launch.

    Creates the canonical demo churches ('grace_umc', 'holy_comforter')
    from YAML seed files if they do not yet exist.
    Returns the list of church_ids that were actually created (may be empty on subsequent calls).

    Seed data is stored in backend/db/seeds/*.yaml files, not in Python code.
    This decouples data from source code.
    """
    created: List[str] = []

    # Map church IDs to their YAML seed files
    seeds = (
        ("grace_umc", "grace_umc.yaml"),
        ("holy_comforter", "holy_comforter.yaml"),
    )

    for church_id, yaml_filename in seeds:
        if _try_resolve_church_pk(church_id) is not None:
            continue
        try:
            from . import seed_loader
            ctx = seed_loader.load_seed_yaml(yaml_filename)
            # Verify church_id matches
            if ctx.church_id != church_id:
                # Update to ensure consistency
                ctx.church_id = church_id
            save_accounting_context(ctx)
            created.append(church_id)
        except Exception:
            # Seeding is best-effort — never block startup.
            continue

    return created


# ---------------------------------------------------------------------------
# Semantic search (ChromaDB delegate)
# ---------------------------------------------------------------------------

def semantic_search(church_id: str, query: str, limit: int = 5) -> List[dict]:
    """Search GL accounts semantically via the per-church ChromaDB index.

    Returns a list of dicts shaped like:
        {account_number, account_name, account_type, fund_id, score}

    Falls back to a SQL ILIKE match when ChromaDB is unavailable so that
    callers can degrade gracefully.
    """
    if _try_resolve_church_pk(church_id) is None:
        raise ValueError(f"Unknown church_id: {church_id}")

    # Preferred path: delegate to the legacy ChromaDB-backed search which
    # is rebuilt on every save_accounting_context() call.
    try:
        from ..tools import coa_store as _legacy  # type: ignore
        hits = _legacy.semantic_search(church_id, query, k=max(1, int(limit)))
        if hits:
            out: List[dict] = []
            for h in hits:
                out.append({
                    "account_number": h.get("account_number") or h.get("account") or "",
                    "account_name": h.get("account_name") or h.get("name") or "",
                    "account_type": h.get("account_type") or "",
                    "description": h.get("description") or h.get("account_name") or "",
                    "fund_id": h.get("fund_id") or "",
                    "score": float(h.get("score") or 0.0),
                })
            return out
    except Exception:
        pass

    # Fallback: relational ILIKE match.
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT account_number, name AS account_name, account_type
          FROM gl_accounts
         WHERE church_id = %s
           AND is_active = true
           AND (name ILIKE %s OR account_number ILIKE %s)
         ORDER BY account_number
         LIMIT %s
        """,
        (church_pk, f"%{query}%", f"%{query}%", max(1, int(limit))),
    ) or []
    return [
        {
            "account_number": r["account_number"],
            "account_name": r.get("account_name") or "",
            "account_type": r.get("account_type") or "",
            "description": r.get("account_name") or "",
            "fund_id": "",
            "score": 0.5,  # heuristic — non-semantic match
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------

def bulk_import_accounts(
    church_id: str,
    accounts: List[Account],
    funds: Optional[List[Fund]] = None,
) -> int:
    """Atomically UPSERT all accounts (and optionally funds) for a church.

    Any pre-existing accounts/funds NOT present in the new list are
    soft-deleted (is_active = false). Returns the number of accounts
    inserted or updated.
    """
    church_pk = _resolve_church_pk(church_id)
    upserted = 0

    with atomic_transaction() as conn:
        cur = conn.cursor()

        # ----- Funds (optional) -----
        if funds is not None:
            seen_fund_ids: List[str] = []
            for fund in funds:
                cur.execute(
                    """
                    INSERT INTO funds (church_id, fund_id, name, category, is_active, updated_at)
                    VALUES (%s, %s, %s, %s, true, CURRENT_TIMESTAMP)
                    ON CONFLICT (church_id, fund_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        is_active = true,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        church_pk,
                        fund.fund_id,
                        fund.fund_name,
                        fund.fund_category.value
                        if hasattr(fund.fund_category, "value")
                        else str(fund.fund_category),
                    ),
                )
                seen_fund_ids.append(fund.fund_id)

            if seen_fund_ids:
                cur.execute(
                    """
                    UPDATE funds SET is_active = false, updated_at = CURRENT_TIMESTAMP
                    WHERE church_id = %s AND fund_id NOT IN %s
                    """,
                    (church_pk, tuple(seen_fund_ids)),
                )

        # ----- Accounts -----
        seen_account_numbers: List[str] = []
        for acct in accounts:
            cur.execute(
                """
                INSERT INTO gl_accounts (
                    church_id, account_number, account_type, name, is_active, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (church_id, account_number) DO UPDATE SET
                    account_type = EXCLUDED.account_type,
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    church_pk,
                    acct.account_number,
                    acct.account_type,
                    acct.account_name,
                    bool(acct.active),
                ),
            )
            seen_account_numbers.append(acct.account_number)
            upserted += 1

        if seen_account_numbers:
            cur.execute(
                """
                UPDATE gl_accounts SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE church_id = %s AND account_number NOT IN %s
                """,
                (church_pk, tuple(seen_account_numbers)),
            )

        cur.close()

    return upserted


# ---------------------------------------------------------------------------
# Budget replace
# ---------------------------------------------------------------------------

def set_budget(church_id: str, budget_plan: BudgetPlan) -> None:
    """Atomically replace the entire budget for a church / fiscal year.

    Deletes the prior budget_plans (cascading to budget_months) for the
    accounting_context and inserts a fresh plan with monthly buckets.
    """
    church_pk = _resolve_church_pk(church_id)
    fiscal_year = int(budget_plan.fiscal_year)

    with atomic_transaction() as conn:
        cur = conn.cursor()

        ac_pk = _ensure_accounting_context_row(cur, church_pk, fiscal_year)

        # Replace strategy: drop prior plans wholesale.
        cur.execute(
            "DELETE FROM budget_plans WHERE accounting_context_id = %s",
            (ac_pk,),
        )
        cur.execute(
            """
            INSERT INTO budget_plans (accounting_context_id)
            VALUES (%s) RETURNING id
            """,
            (ac_pk,),
        )
        bp_pk = int(cur.fetchone()[0])

        for acct_num, bm in (budget_plan.accounts or {}).items():
            for m_idx, attr in enumerate(_MONTH_ATTRS, start=1):
                amt = getattr(bm, attr, Decimal("0")) or Decimal("0")
                if amt == Decimal("0"):
                    continue
                cur.execute(
                    """
                    INSERT INTO budget_months (
                        budget_plan_id, account_number, month, budgeted_amount
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (bp_pk, acct_num, m_idx, _decimal(amt)),
                )

        cur.close()


# ---------------------------------------------------------------------------
# Variance report (SQL-side aggregation)
# ---------------------------------------------------------------------------

def get_variance_report(church_id: str) -> List[dict]:
    """Return a SQL-aggregated variance report for the latest fiscal year.

    Output records contain:
        account_number, account_type, budgeted, actual, variance_pct, status

    Status buckets:
        NO_BUDGET        - budgeted == 0
        WITHIN_10%       - |variance_pct| <= 10
        WARNING_10_25%   - 10 <  |variance_pct| <= 25
        OVER_25%         - |variance_pct| > 25

    `variance_pct` is signed: positive = over budget (actual > budgeted).
    """
    church_pk = _resolve_church_pk(church_id)

    # Pick the most recent fiscal_year on file for this church.
    fy_row = execute_query(
        """
        SELECT MAX(fiscal_year) AS fy
          FROM accounting_contexts
         WHERE church_id = %s
        """,
        (church_pk,),
        fetch_one=True,
    )
    fiscal_year = int(fy_row["fy"]) if fy_row and fy_row.get("fy") is not None else None
    if fiscal_year is None:
        return []

    rows = execute_query(
        """
        WITH bm AS (
            SELECT bm.account_number,
                   SUM(bm.budgeted_amount) AS budgeted
              FROM budget_months bm
              JOIN budget_plans bp ON bp.id = bm.budget_plan_id
              JOIN accounting_contexts ac ON ac.id = bp.accounting_context_id
             WHERE ac.church_id = %s AND ac.fiscal_year = %s
             GROUP BY bm.account_number
        ),
        ya AS (
            SELECT account_number, SUM(amount) AS actual
              FROM ytd_actuals
             WHERE church_id = %s AND fiscal_year = %s
             GROUP BY account_number
        ),
        agg AS (
            SELECT COALESCE(bm.account_number, ya.account_number) AS account_number,
                   COALESCE(bm.budgeted, 0) AS budgeted,
                   COALESCE(ya.actual, 0)   AS actual
              FROM bm FULL OUTER JOIN ya ON bm.account_number = ya.account_number
        )
        SELECT agg.account_number,
               COALESCE(g.account_type, '') AS account_type,
               agg.budgeted,
               agg.actual,
               CASE
                   WHEN agg.budgeted = 0 THEN NULL
                   ELSE ((agg.actual - agg.budgeted) / agg.budgeted) * 100.0
               END AS variance_pct
          FROM agg
          LEFT JOIN gl_accounts g
            ON g.church_id = %s AND g.account_number = agg.account_number
         ORDER BY agg.account_number
        """,
        (church_pk, fiscal_year, church_pk, fiscal_year, church_pk),
    ) or []

    out: List[dict] = []
    for r in rows:
        budgeted = _decimal(r["budgeted"])
        actual = _decimal(r["actual"])
        vpct_raw = r.get("variance_pct")
        if vpct_raw is None or budgeted == 0:
            status = "NO_BUDGET"
            variance_pct: Optional[float] = None
        else:
            variance_pct = float(vpct_raw)
            mag = abs(variance_pct)
            if mag <= 10.0:
                status = "WITHIN_10%"
            elif mag <= 25.0:
                status = "WARNING_10_25%"
            else:
                status = "OVER_25%"

        out.append({
            "account_number": r["account_number"],
            "account_type": r.get("account_type") or "",
            "budgeted": budgeted,
            "actual": actual,
            "variance_pct": variance_pct,
            "status": status,
        })
    return out
