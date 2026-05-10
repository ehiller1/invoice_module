"""PostgreSQL-backed reconciliation matches store.

Replaces the JSON-dict scheme of previous implementations. Stores matches
between Plaid transactions and journal entries.

Schema reference:
- recon_matches(id PK, church_id FK, plaid_txn_id FK, journal_entry_id FK,
  amount_diff, days_diff, matched_at)
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .connection import execute_query
from ..models.schemas import PlaidTransaction


def _resolve_church_pk(church_id: str) -> int:
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _row_to_plaid_txn(row: Dict[str, Any]) -> PlaidTransaction:
    return PlaidTransaction(
        txn_id=row["txn_id"],
        account_id=row.get("plaid_account_external_id") or "",
        date=row["date"],
        description=row.get("description") or "",
        amount=float(row.get("amount") or 0.0),
        category=row.get("category") or "",
        merchant_name=row.get("merchant_name"),
        fetched_at=row.get("fetched_at") or datetime.utcnow(),
    )


def load_matches(church_id: str) -> Dict[str, Dict[str, Any]]:
    """Load all matches for a church, keyed by plaid txn external txn_id.

    Returned shape:
        {
            "<plaid_txn_external_id>": {
                "je_id": "<journal_entries.entry_id>",
                "amount_diff": Decimal | None,
                "days_diff": int | None,
                "matched_at": datetime,
            },
            ...
        }
    """
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT pt.txn_id AS plaid_txn_external_id,
               je.entry_id AS je_external_id,
               rm.amount_diff,
               rm.days_diff,
               rm.matched_at
          FROM recon_matches rm
          JOIN plaid_transactions pt ON pt.id = rm.plaid_txn_id
          LEFT JOIN journal_entries je ON je.id = rm.journal_entry_id
         WHERE rm.church_id = %s
        """,
        (church_pk,),
    ) or []

    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out[r["plaid_txn_external_id"]] = {
            "je_id": r.get("je_external_id"),
            "amount_diff": r.get("amount_diff"),
            "days_diff": r.get("days_diff"),
            "matched_at": r.get("matched_at"),
        }
    return out


def save_match(
    church_id: str,
    plaid_txn_id: int,
    journal_entry_id: int,
    amount_diff: Optional[Decimal] = None,
    days_diff: Optional[int] = None,
) -> None:
    """Insert or update a match.

    `plaid_txn_id` and `journal_entry_id` are the SERIAL PK ids from the
    `plaid_transactions` and `journal_entries` tables respectively.
    """
    church_pk = _resolve_church_pk(church_id)

    # The schema does not declare a UNIQUE constraint on (plaid_txn_id, journal_entry_id),
    # so we emulate UPSERT by deleting any prior row for this plaid_txn_id, then inserting.
    execute_query(
        "DELETE FROM recon_matches WHERE church_id = %s AND plaid_txn_id = %s",
        (church_pk, plaid_txn_id),
    )
    execute_query(
        """
        INSERT INTO recon_matches (
            church_id, plaid_txn_id, journal_entry_id,
            amount_diff, days_diff, matched_at
        ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """,
        (
            church_pk,
            plaid_txn_id,
            journal_entry_id,
            amount_diff,
            days_diff,
        ),
    )


def list_unmatched_txns(church_id: str) -> List[PlaidTransaction]:
    """Return Plaid transactions for this church with no recon_matches row."""
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT pt.id, pt.txn_id, pt.date, pt.description, pt.amount,
               pt.category, pt.merchant_name, pt.fetched_at,
               pa.account_id AS plaid_account_external_id
          FROM plaid_transactions pt
          JOIN plaid_accounts pa ON pa.id = pt.account_id
          LEFT JOIN recon_matches rm ON rm.plaid_txn_id = pt.id
         WHERE pt.church_id = %s
           AND rm.id IS NULL
         ORDER BY pt.date DESC, pt.id DESC
        """,
        (church_pk,),
    ) or []
    return [_row_to_plaid_txn(r) for r in rows]


def find_matching_entries(church_id: str, transaction: PlaidTransaction) -> List[Dict[str, Any]]:
    """Find JEs that match a Plaid transaction within tolerances.

    Matching criteria:
    - Amount: |txn.amount - je.total_debits| < 0.01
    - Date: |txn.date - je.entry_date| <= 3 days
    - JE must be BALANCED status
    - No existing match in recon_matches

    Args:
        church_id: Church identifier
        transaction: PlaidTransaction to match

    Returns:
        List of matching JE dicts sorted by amount_diff, then days_diff.
        Each dict contains: je_id (int PK), entry_id (str), total_debits,
        entry_date, amount_diff, days_diff.
    """
    church_pk = _resolve_church_pk(church_id)

    # Plaid: positive amount = outflow; we match against absolute cash amount,
    # consistent with the previous nested-loop implementation.
    txn_amount = abs(float(transaction.amount))
    txn_date = transaction.date

    # Phase 5c: accept any non-rejected, non-cancelled JE so the matcher
    # works against the model statuses the rest of the system actually
    # produces (APPROVED / POSTED / OPEN). Phase 4 only accepted 'BALANCED'
    # which the JE store never emits — this was a latent dead code path.
    query = """
    SELECT
        je.id AS je_id,
        je.entry_id,
        je.total_debits,
        je.entry_date,
        ABS(je.total_debits - %s::numeric) AS amount_diff,
        ABS((je.entry_date - %s::date)) AS days_diff
    FROM journal_entries je
    WHERE je.church_id = %s
      AND je.is_balanced = TRUE
      AND je.status NOT IN ('REJECTED', 'CANCELLED')
      AND ABS(je.total_debits - %s::numeric) < 0.01
      AND ABS((je.entry_date - %s::date)) <= 3
      AND NOT EXISTS (
        SELECT 1 FROM recon_matches rm
        WHERE rm.journal_entry_id = je.id
          AND rm.church_id = %s
      )
    ORDER BY amount_diff ASC, days_diff ASC
    """

    rows = execute_query(
        query,
        (
            txn_amount,
            txn_date,
            church_pk,
            txn_amount,
            txn_date,
            church_pk,
        ),
    ) or []
    return rows


def delete_match(church_id: str, plaid_txn_id: int) -> bool:
    """Unmatch a transaction by deleting its recon_matches row(s)."""
    church_pk = _resolve_church_pk(church_id)
    count = execute_query(
        "DELETE FROM recon_matches WHERE church_id = %s AND plaid_txn_id = %s",
        (church_pk, plaid_txn_id),
    )
    return bool(count and count > 0)
