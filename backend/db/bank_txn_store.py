"""PostgreSQL-backed BankTransaction persistence.

Append-only store for bank-statement-derived transactions (CSV/OFX/QFX).
Also exposes a helper for finding bank txns that have not yet been matched
to a journal entry via `recon_matches`.

Schema reference:
- bank_transactions(id PK, txn_id, church_id FK, date, description, amount,
  type, source_filename, raw, created_at)
- recon_matches(id PK, church_id FK, plaid_txn_id FK, journal_entry_id FK,
  amount_diff, days_diff, matched_at)

Note: `recon_matches` references `plaid_transactions`, not `bank_transactions`.
The "unmatched bank transactions" query therefore returns all bank rows that
have no corresponding plaid_transaction with the same (date, amount) that has
been matched. We use a conservative join: a bank txn is "matched" if there is
any recon_matches row whose plaid_txn shares this church_id and (date, amount).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .connection import execute_query
from .transactions import atomic_transaction
from ..models.schemas import BankTransaction


def _resolve_church_pk(church_id: str) -> int:
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _row_to_bank_txn(row: Dict[str, Any]) -> BankTransaction:
    raw = row.get("raw")
    if isinstance(raw, str) and raw:
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {"_raw": raw}
    elif raw is None:
        raw = None
    return BankTransaction(
        txn_id=row["txn_id"] or "",
        date=row["date"],
        description=row.get("description") or "",
        amount=Decimal(str(row.get("amount") or "0")),
        type=row.get("type") or "DEBIT",
        raw=raw,
        source_filename=row.get("source_filename"),
    )


def save_bank_transactions(
    church_id: str,
    transactions: List[BankTransaction],
) -> int:
    """Append bank-statement transactions. Returns number of inserted rows.

    No de-duplication: this store is append-only. If a statement is uploaded
    twice, both rows will be persisted; callers are responsible for guarding
    re-uploads when needed.
    """
    if not transactions:
        return 0
    church_pk = _resolve_church_pk(church_id)

    n = 0
    with atomic_transaction() as conn:
        cur = conn.cursor()
        for t in transactions:
            raw_json = json.dumps(t.raw, default=str) if t.raw else None
            cur.execute(
                """
                INSERT INTO bank_transactions (
                    txn_id, church_id, date, description, amount,
                    type, source_filename, raw
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
                """,
                (
                    t.txn_id or None,
                    church_pk,
                    t.date,
                    t.description or "",
                    Decimal(str(t.amount)),
                    t.type or "DEBIT",
                    t.source_filename,
                    raw_json,
                ),
            )
            n += cur.rowcount or 0
        cur.close()
    return n


def load_bank_transactions(
    church_id: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[BankTransaction]:
    """Load bank transactions for a church with optional date filters."""
    church_pk = _resolve_church_pk(church_id)

    sql = ["SELECT * FROM bank_transactions WHERE church_id = %s"]
    params: List[Any] = [church_pk]
    if date_from:
        sql.append("AND date >= %s")
        params.append(date_from)
    if date_to:
        sql.append("AND date <= %s")
        params.append(date_to)
    sql.append("ORDER BY date DESC, id DESC")

    rows = execute_query(" ".join(sql), tuple(params)) or []
    return [_row_to_bank_txn(r) for r in rows]


def get_unmatched_transactions(church_id: str) -> List[BankTransaction]:
    """Return bank transactions with no corresponding matched plaid txn.

    A bank txn is considered "matched" if there is a recon_matches row whose
    plaid_transaction has the same church_id, date, and amount.
    """
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT bt.*
          FROM bank_transactions bt
         WHERE bt.church_id = %s
           AND NOT EXISTS (
                 SELECT 1
                   FROM recon_matches rm
                   JOIN plaid_transactions pt ON pt.id = rm.plaid_txn_id
                  WHERE rm.church_id = bt.church_id
                    AND pt.date = bt.date
                    AND pt.amount = bt.amount
               )
         ORDER BY bt.date DESC, bt.id DESC
        """,
        (church_pk,),
    ) or []
    return [_row_to_bank_txn(r) for r in rows]
