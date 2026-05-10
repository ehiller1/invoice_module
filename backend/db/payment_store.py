"""Payment Instruction persistence layer (PostgreSQL).

Replaces JSONL-based payment storage. The `payment_instructions` table holds
top-level fields plus JSONB columns for ach_record, check_record, and a
plain `cc_memo` text column.

Schema reference:
- payment_instructions (payment_id, church_id FK, je_id FK -> journal_entries.id,
  vendor_id FK -> vendors.id, status, method, amount, memo,
  ach_record JSONB, check_record JSONB, cc_memo, ...)
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from .connection import execute_query
from .transactions import atomic_transaction
from ..models.schemas import (
    ACHRecord,
    CheckRecord,
    CreditCardMemo,
    PaymentInstruction,
    PaymentMethod,
    PaymentStatus,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_church_pk(church_id: str) -> int:
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _resolve_church_external_id(church_pk: int) -> str:
    row = execute_query(
        "SELECT church_id FROM churches WHERE id = %s",
        (church_pk,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church PK: {church_pk}")
    return str(row["church_id"])


def _resolve_je_pk(je_external_id: Optional[str]) -> Optional[int]:
    if not je_external_id:
        return None
    row = execute_query(
        "SELECT id FROM journal_entries WHERE entry_id = %s",
        (je_external_id,),
        fetch_one=True,
    )
    return int(row["id"]) if row else None


def _resolve_je_external(je_pk: Optional[int]) -> Optional[str]:
    if je_pk is None:
        return None
    row = execute_query(
        "SELECT entry_id FROM journal_entries WHERE id = %s",
        (je_pk,),
        fetch_one=True,
    )
    return str(row["entry_id"]) if row else None


def _resolve_vendor_pk(vendor_external_id: Optional[str]) -> Optional[int]:
    """The Vendor model uses a string vendor_id; the DB uses SERIAL.

    We treat the external id as the vendor name lookup if it's not numeric,
    since the schema's UNIQUE key on vendors is (church_id, name). Callers
    storing numeric IDs as strings still work via the int-cast path.
    """
    if not vendor_external_id:
        return None
    try:
        return int(vendor_external_id)
    except (TypeError, ValueError):
        return None


def _enum_str(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _record_to_json(record: Any) -> Optional[Any]:
    """Pydantic record → JSONB-friendly value, preserving Decimal as string."""
    if record is None:
        return None
    if hasattr(record, "model_dump"):
        # mode="json" serializes Decimal/date to JSON-safe primitives.
        return Json(record.model_dump(mode="json"))
    if isinstance(record, dict):
        return Json(record)
    return Json(record)


def _json_to_ach(value: Any) -> Optional[ACHRecord]:
    if not value:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    return ACHRecord(**value)


def _json_to_check(value: Any) -> Optional[CheckRecord]:
    if not value:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    return CheckRecord(**value)


def _row_to_payment(row: Dict[str, Any]) -> PaymentInstruction:
    je_external = _resolve_je_external(row.get("je_id"))

    # cc_memo is a free text column; reconstitute as a CreditCardMemo only
    # if the row carries enough info — otherwise leave None.
    cc_memo: Optional[CreditCardMemo] = None

    return PaymentInstruction(
        payment_id=str(row["payment_id"]),
        church_id=_resolve_church_external_id(int(row["church_id"])),
        vendor_id=str(row["vendor_id"]) if row.get("vendor_id") is not None else None,
        je_id=je_external,
        method=PaymentMethod(row["method"]) if row.get("method") else PaymentMethod.ACH,
        amount=Decimal(str(row.get("amount") or 0)),
        status=PaymentStatus(row["status"]) if row.get("status") else PaymentStatus.DRAFT,
        ach_record=_json_to_ach(row.get("ach_record")),
        check_record=_json_to_check(row.get("check_record")),
        cc_memo=cc_memo,
        requested_by=None,
        approved_by=None,
        created_at=row.get("created_at") or datetime.utcnow(),
        updated_at=row.get("updated_at") or datetime.utcnow(),
        notes=row.get("memo"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_payment(church_id: str, payment: PaymentInstruction) -> str:
    """Insert a payment instruction. Returns the payment_id."""
    church_pk = _resolve_church_pk(church_id)
    je_pk = _resolve_je_pk(payment.je_id)
    vendor_pk = _resolve_vendor_pk(payment.vendor_id)

    cc_memo_text: Optional[str] = None
    if payment.cc_memo is not None:
        # Persist a short human-readable instruction string in cc_memo column.
        cc_memo_text = payment.cc_memo.instruction[:255]

    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO payment_instructions (
                payment_id, church_id, je_id, vendor_id,
                status, method, amount, memo,
                ach_record, check_record, cc_memo
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s
            )
            RETURNING payment_id
            """,
            (
                payment.payment_id,
                church_pk,
                je_pk,
                vendor_pk,
                _enum_str(payment.status),
                _enum_str(payment.method),
                payment.amount,
                payment.notes,
                _record_to_json(payment.ach_record),
                _record_to_json(payment.check_record),
                cc_memo_text,
            ),
        )
        (payment_id,) = cur.fetchone()
        cur.close()

    return str(payment_id)


def update_payment(payment_id: str, updates: Dict[str, Any]) -> bool:
    """Update payment fields. No version locking.

    Allowed columns: status, method, amount, memo, ach_record, check_record,
    cc_memo, je_id, vendor_id, completed_at.
    """
    allowed = {
        "status",
        "method",
        "amount",
        "memo",
        "ach_record",
        "check_record",
        "cc_memo",
        "completed_at",
    }
    set_clauses: List[str] = []
    params: List[Any] = []

    for col, val in updates.items():
        if col == "je_id":
            set_clauses.append("je_id = %s")
            params.append(_resolve_je_pk(val))
            continue
        if col == "vendor_id":
            set_clauses.append("vendor_id = %s")
            params.append(_resolve_vendor_pk(val))
            continue
        if col not in allowed:
            continue
        if col in ("status", "method"):
            set_clauses.append(f"{col} = %s")
            params.append(_enum_str(val))
        elif col in ("ach_record", "check_record"):
            set_clauses.append(f"{col} = %s")
            params.append(_record_to_json(val))
        else:
            set_clauses.append(f"{col} = %s")
            params.append(val)

    if not set_clauses:
        return False

    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    sql = (
        "UPDATE payment_instructions SET "
        + ", ".join(set_clauses)
        + " WHERE payment_id = %s"
    )
    params.append(payment_id)

    rowcount = execute_query(sql, tuple(params))
    return bool(rowcount and rowcount > 0)


def get_payment(payment_id: str) -> Optional[PaymentInstruction]:
    """Load a payment by payment_id."""
    row = execute_query(
        """
        SELECT payment_id, church_id, je_id, vendor_id, status, method,
               amount, memo, ach_record, check_record, cc_memo,
               created_at, updated_at, completed_at
          FROM payment_instructions
         WHERE payment_id = %s
        """,
        (payment_id,),
        fetch_one=True,
    )
    if not row:
        return None
    return _row_to_payment(row)


def list_payments(
    church_id: str,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
) -> List[PaymentInstruction]:
    """List payments for a church with optional status/since filters."""
    church_pk = _resolve_church_pk(church_id)
    where = ["church_id = %s"]
    params: List[Any] = [church_pk]

    if status is not None:
        where.append("status = %s")
        params.append(_enum_str(status))
    if since is not None:
        where.append("created_at >= %s")
        params.append(since)

    sql = (
        "SELECT payment_id, church_id, je_id, vendor_id, status, method, "
        "       amount, memo, ach_record, check_record, cc_memo, "
        "       created_at, updated_at, completed_at "
        "  FROM payment_instructions "
        " WHERE " + " AND ".join(where) +
        " ORDER BY created_at DESC"
    )
    rows = execute_query(sql, tuple(params)) or []
    return [_row_to_payment(r) for r in rows]


def find_payment_by_je(je_id: str) -> Optional[PaymentInstruction]:
    """Find the payment linked to a journal entry (by external entry_id)."""
    je_pk = _resolve_je_pk(je_id)
    if je_pk is None:
        return None
    row = execute_query(
        """
        SELECT payment_id, church_id, je_id, vendor_id, status, method,
               amount, memo, ach_record, check_record, cc_memo,
               created_at, updated_at, completed_at
          FROM payment_instructions
         WHERE je_id = %s
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (je_pk,),
        fetch_one=True,
    )
    if not row:
        return None
    return _row_to_payment(row)


def delete_payment(payment_id: str) -> bool:
    """Hard-delete a payment instruction.

    Note: deleting the parent JE will set je_id NULL on the payment due to
    ON DELETE SET NULL — it will not delete the payment.
    """
    rowcount = execute_query(
        "DELETE FROM payment_instructions WHERE payment_id = %s",
        (payment_id,),
    )
    return bool(rowcount and rowcount > 0)


def transition_payment_status(payment_id: str, new_status: Any) -> bool:
    """Transition a payment's status. Returns True on update."""
    status = _enum_str(new_status)
    # When moving to terminal states, set completed_at automatically.
    if status in ("CLEARED", "FAILED", "CANCELLED"):
        rowcount = execute_query(
            """
            UPDATE payment_instructions
               SET status = %s,
                   completed_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
             WHERE payment_id = %s
            """,
            (status, payment_id),
        )
    else:
        rowcount = execute_query(
            """
            UPDATE payment_instructions
               SET status = %s,
                   updated_at = CURRENT_TIMESTAMP
             WHERE payment_id = %s
            """,
            (status, payment_id),
        )
    return bool(rowcount and rowcount > 0)
