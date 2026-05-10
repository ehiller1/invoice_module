"""PostgreSQL-backed Plaid persistence (refactored from JSON file store).

Stores Plaid-linked bank accounts and their transactions. Access tokens are
Fernet-encrypted on write and decrypted on read. Encryption helpers are
re-used from `backend/tools/plaid_store.py` so a single key rotation rotates
both the legacy JSON store and this DB-backed store.

Schema reference:
- plaid_accounts(id PK, church_id FK, account_id UNIQUE per church,
  access_token_enc, account_number, routing_number, account_type,
  account_subtype, mask, name, current_balance, available_balance,
  is_ach_enabled, last_synced_at, created_at, updated_at)
- plaid_transactions(id PK, txn_id, church_id FK, account_id FK,
  date, description, amount, category, merchant_name, fetched_at, created_at,
  UNIQUE(account_id, txn_id))
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .connection import execute_query
from .transactions import atomic_transaction
from ..events.emitter import emit_event_in_txn
from ..events.schemas import EventType, FinancialEvent, TagKind
from ..models.schemas import PlaidAccount, PlaidTransaction
from ..tools.plaid_store import encrypt_token, decrypt_token


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_church_pk(church_id: str) -> int:
    """Resolve string church_id → SERIAL PK from the churches table."""
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _resolve_account_pk(church_pk: int, account_id: str) -> Optional[int]:
    row = execute_query(
        "SELECT id FROM plaid_accounts WHERE church_id = %s AND account_id = %s",
        (church_pk, account_id),
        fetch_one=True,
    )
    return int(row["id"]) if row else None


def _row_to_account(row: Dict[str, Any]) -> PlaidAccount:
    """Reconstruct a PlaidAccount from a plaid_accounts row.

    Decrypts access_token_enc into the model field (which is named
    `access_token_enc` and treated as the in-memory encrypted form by callers
    that re-encrypt; here we expose the *decrypted* token because the legacy
    file-based store also returned the encrypted-form-as-stored token. Callers
    that need plaintext should use `decrypt_token`. To preserve the existing
    contract we leave the *encrypted* form on the model, matching legacy.)
    """
    enc = row.get("access_token_enc") or ""
    return PlaidAccount(
        account_id=row["account_id"],
        church_id=str(row.get("church_external_id") or ""),
        access_token_enc=enc,  # remains encrypted in the model field
        account_number=row.get("account_number") or "",
        routing_number=row.get("routing_number") or "",
        account_type=row.get("account_type") or "depository",
        account_subtype=row.get("account_subtype") or "checking",
        mask=row.get("mask") or "",
        name=row.get("name") or "",
        current_balance=float(row.get("current_balance") or 0.0),
        available_balance=float(row.get("available_balance") or 0.0),
        balance_updated_at=row.get("last_synced_at") or datetime.utcnow(),
        linked_at=row.get("created_at") or datetime.utcnow(),
        is_ach_enabled=bool(row.get("is_ach_enabled", True)),
        created_at=row.get("created_at") or datetime.utcnow(),
    )


def _row_to_txn(row: Dict[str, Any]) -> PlaidTransaction:
    return PlaidTransaction(
        txn_id=row["txn_id"],
        account_id=row["plaid_account_external_id"]
        if "plaid_account_external_id" in row
        else row.get("account_id_str") or "",
        date=row["date"],
        description=row.get("description") or "",
        amount=float(row.get("amount") or 0.0),
        category=row.get("category") or "",
        merchant_name=row.get("merchant_name"),
        fetched_at=row.get("fetched_at") or datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def load_plaid_accounts(church_id: str) -> List[PlaidAccount]:
    """Load all Plaid accounts for a church (token field stays encrypted)."""
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT pa.*, c.church_id AS church_external_id
          FROM plaid_accounts pa
          JOIN churches c ON c.id = pa.church_id
         WHERE pa.church_id = %s
         ORDER BY pa.created_at ASC
        """,
        (church_pk,),
    ) or []
    return [_row_to_account(r) for r in rows]


def get_plaid_account(church_id: str, account_id: str) -> Optional[PlaidAccount]:
    """Load a single Plaid account by external account_id."""
    church_pk = _resolve_church_pk(church_id)
    row = execute_query(
        """
        SELECT pa.*, c.church_id AS church_external_id
          FROM plaid_accounts pa
          JOIN churches c ON c.id = pa.church_id
         WHERE pa.church_id = %s AND pa.account_id = %s
        """,
        (church_pk, account_id),
        fetch_one=True,
    )
    return _row_to_account(row) if row else None


def save_plaid_account(church_id: str, account: PlaidAccount) -> None:
    """Insert or update a Plaid account.

    The model's `access_token_enc` is treated as already-encrypted if it looks
    like a Fernet token; otherwise we encrypt it before persisting. This makes
    the function tolerant of both call sites: callers that pre-encrypt and
    callers that pass a plaintext token.
    """
    church_pk = _resolve_church_pk(church_id)
    token_enc = account.access_token_enc or ""
    if token_enc and not _looks_encrypted(token_enc):
        token_enc = encrypt_token(token_enc)

    execute_query(
        """
        INSERT INTO plaid_accounts (
            church_id, account_id, access_token_enc,
            account_number, routing_number, account_type, account_subtype,
            mask, name, current_balance, available_balance,
            is_ach_enabled, last_synced_at
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s
        )
        ON CONFLICT (church_id, account_id) DO UPDATE SET
            access_token_enc = COALESCE(NULLIF(EXCLUDED.access_token_enc, ''), plaid_accounts.access_token_enc),
            account_number = EXCLUDED.account_number,
            routing_number = EXCLUDED.routing_number,
            account_type = EXCLUDED.account_type,
            account_subtype = EXCLUDED.account_subtype,
            mask = EXCLUDED.mask,
            name = EXCLUDED.name,
            current_balance = EXCLUDED.current_balance,
            available_balance = EXCLUDED.available_balance,
            is_ach_enabled = EXCLUDED.is_ach_enabled,
            last_synced_at = EXCLUDED.last_synced_at,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            church_pk,
            account.account_id,
            token_enc,
            account.account_number or "",
            account.routing_number or "",
            account.account_type,
            account.account_subtype,
            account.mask or "",
            account.name or "",
            Decimal(str(account.current_balance or 0.0)),
            Decimal(str(account.available_balance or 0.0)),
            bool(account.is_ach_enabled),
            account.balance_updated_at or datetime.utcnow(),
        ),
    )


def _looks_encrypted(token: str) -> bool:
    """Heuristic: Fernet tokens start with 'gAAAAA' (urlsafe-b64 of 0x80 0x00 0x00 0x00 0x00)
    or our PLAIN: prefix (which is also stored as-is)."""
    return token.startswith("gAAAAA") or token.startswith("PLAIN:")


def delete_plaid_account(church_id: str, account_id: str) -> bool:
    """Delete a Plaid account; cascades to its transactions."""
    church_pk = _resolve_church_pk(church_id)
    count = execute_query(
        "DELETE FROM plaid_accounts WHERE church_id = %s AND account_id = %s",
        (church_pk, account_id),
    )
    return bool(count and count > 0)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def load_plaid_transactions(
    church_id: str,
    account_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[PlaidTransaction]:
    """Load Plaid transactions for a church with optional filters."""
    church_pk = _resolve_church_pk(church_id)

    sql = [
        """
        SELECT pt.id, pt.txn_id, pt.date, pt.description, pt.amount,
               pt.category, pt.merchant_name, pt.fetched_at,
               pa.account_id AS plaid_account_external_id
          FROM plaid_transactions pt
          JOIN plaid_accounts pa ON pa.id = pt.account_id
         WHERE pt.church_id = %s
        """
    ]
    params: List[Any] = [church_pk]
    if account_id:
        sql.append("AND pa.account_id = %s")
        params.append(account_id)
    if date_from:
        sql.append("AND pt.date >= %s")
        params.append(date_from)
    if date_to:
        sql.append("AND pt.date <= %s")
        params.append(date_to)
    sql.append("ORDER BY pt.date DESC, pt.id DESC")

    rows = execute_query(" ".join(sql), tuple(params)) or []
    return [_row_to_txn(r) for r in rows]


def save_plaid_transactions(
    church_id: str,
    account_id: str,
    transactions: List[PlaidTransaction],
) -> int:
    """Upsert transactions for an account on (account_id, txn_id).

    Returns the number of rows inserted+updated.
    """
    if not transactions:
        return 0
    church_pk = _resolve_church_pk(church_id)
    acct_pk = _resolve_account_pk(church_pk, account_id)
    if acct_pk is None:
        raise ValueError(f"Unknown plaid account: {account_id}")

    n = 0
    with atomic_transaction() as conn:
        cur = conn.cursor()
        for t in transactions:
            cur.execute(
                """
                INSERT INTO plaid_transactions (
                    txn_id, church_id, account_id,
                    date, description, amount, category, merchant_name, fetched_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (account_id, txn_id) DO UPDATE SET
                    date = EXCLUDED.date,
                    description = EXCLUDED.description,
                    amount = EXCLUDED.amount,
                    category = EXCLUDED.category,
                    merchant_name = EXCLUDED.merchant_name,
                    fetched_at = EXCLUDED.fetched_at
                """,
                (
                    t.txn_id,
                    church_pk,
                    acct_pk,
                    t.date,
                    t.description or "",
                    Decimal(str(t.amount or 0.0)),
                    t.category or "",
                    t.merchant_name,
                    t.fetched_at or datetime.utcnow(),
                ),
            )
            n += cur.rowcount or 0

            # Phase 5c: emit BankItemObserved for every Plaid txn write.
            # The structural matcher consumes these to pair against JEs
            # without requiring a human button click.
            ev = FinancialEvent(
                event_type=EventType.BANK_ITEM_OBSERVED,
                church_id=church_id,
                payload={
                    "source": "plaid",
                    "plaid_account_id": account_id,
                    "txn_id": t.txn_id,
                    "date": t.date.isoformat() if t.date else None,
                    "amount": str(t.amount or 0),
                    "description": t.description or "",
                    "merchant_name": t.merchant_name or "",
                    "category": t.category or "",
                },
                correlation_id=t.txn_id,
            )
            ev.add_tag(TagKind.VENDOR, t.merchant_name or "")
            if t.date:
                ev.add_tag(TagKind.PERIOD, f"{t.date.year:04d}-{t.date.month:02d}")
            emit_event_in_txn(conn, ev)
        cur.close()
    return n


def sync_plaid_transactions(
    church_id: str,
    account_id: str,
    new_txns: List[PlaidTransaction],
) -> int:
    """Merge fresh Plaid transactions and bump last_synced_at on the account.

    Phase 5c: after persistence, automatically run the structural matcher.
    The user no longer clicks "Auto-Match" — structural agreement is
    continuous. Failures inside the matcher are swallowed so a sync that
    succeeds at writing rows isn't reported as failed.

    Returns the number of rows inserted+updated.
    """
    n = save_plaid_transactions(church_id, account_id, new_txns)
    church_pk = _resolve_church_pk(church_id)
    execute_query(
        """
        UPDATE plaid_accounts
           SET last_synced_at = CURRENT_TIMESTAMP,
               updated_at = CURRENT_TIMESTAMP
         WHERE church_id = %s AND account_id = %s
        """,
        (church_pk, account_id),
    )
    if new_txns:
        try:
            from ..events.structural_match import run_for_church
            run_for_church(church_id, account_id=account_id)
        except Exception:
            pass
    return n


def fetch_and_store_transactions(
    church_id: str,
    account_id: str,
    plaid_api_fn,
) -> int:
    """Call a caller-provided Plaid fetcher and store its results.

    `plaid_api_fn(access_token: str) -> List[PlaidTransaction]` is invoked with
    the decrypted access token for `account_id`. The returned transactions are
    upserted, and `last_synced_at` is updated. Returns the number of rows
    inserted+updated.
    """
    acct = get_plaid_account(church_id, account_id)
    if acct is None:
        raise ValueError(f"Unknown plaid account: {account_id}")
    access = decrypt_token(acct.access_token_enc) if acct.access_token_enc else ""
    fetched = plaid_api_fn(access) or []
    return sync_plaid_transactions(church_id, account_id, fetched)
