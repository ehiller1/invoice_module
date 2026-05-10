"""Journal Entry persistence layer (PostgreSQL).

Replaces JSONL-based journal entry storage. Implements CRUD with optimistic
locking via the `version` column on `journal_entries`.

Schema reference:
- journal_entries (entry_id, church_id, status, entry_date, total_debits,
  total_credits, is_balanced, version, ...)
- journal_entry_lines (journal_entry_id FK, account_number, fund_id,
  debit, credit, description, line_no, ...)

Status enum (DB):
  'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'BALANCED', 'POSTED', 'REJECTED', 'CANCELLED'

Note: the `JournalEntry` Pydantic model uses a slightly different status enum
(JEStatus). Where DB and model status names diverge, the model's `_missing_`
hook handles legacy "PENDING_APPROVAL" → OPEN. We persist the enum's value
verbatim; callers are responsible for sending statuses the DB enum accepts.
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
    JournalEntry,
    JournalEntryLine,
    JEStatus,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_church_pk(church_id: str) -> int:
    """Resolve string church_id → SERIAL PK from the churches table.

    Raises ValueError if the church does not exist.
    """
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _resolve_church_external_id(church_pk: int) -> str:
    """Reverse resolve SERIAL PK → string church_id."""
    row = execute_query(
        "SELECT church_id FROM churches WHERE id = %s",
        (church_pk,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church PK: {church_pk}")
    return str(row["church_id"])


def _status_str(status: Any) -> str:
    """Coerce a status (Enum or str) to its raw value for the DB enum."""
    if isinstance(status, JEStatus):
        return status.value
    if hasattr(status, "value"):
        return str(status.value)
    return str(status)


def _line_to_row(je_pk: int, line: JournalEntryLine) -> tuple:
    """Project a JournalEntryLine onto the journal_entry_lines schema."""
    return (
        je_pk,
        line.account_number,
        line.fund_id,
        line.debit if line.debit else Decimal("0"),
        line.credit if line.credit else Decimal("0"),
        line.memo or "",
        line.sequence,
    )


def _row_to_line(row: Dict[str, Any]) -> JournalEntryLine:
    """Reconstruct a JournalEntryLine from a journal_entry_lines row.

    The DB row does not store account_name / fund_name (those live in the
    coa/funds tables), so we leave them blank for round-trip; callers that
    need them should re-hydrate from coa_store.
    """
    return JournalEntryLine(
        sequence=int(row.get("line_no") or 0),
        account_number=str(row["account_number"]),
        account_name="",
        fund_id=str(row.get("fund_id") or ""),
        fund_name="",
        debit=Decimal(str(row.get("debit") or 0)),
        credit=Decimal(str(row.get("credit") or 0)),
        memo=str(row.get("description") or ""),
        approved_by=None,
    )


def _row_to_je(je_row: Dict[str, Any], lines: List[JournalEntryLine]) -> JournalEntry:
    """Reconstruct a JournalEntry from a journal_entries row + its lines."""
    church_external = _resolve_church_external_id(int(je_row["church_id"]))

    # Build accounting_period as YYYY-MM if we have year + period
    fy = je_row.get("fiscal_year")
    period = je_row.get("accounting_period")
    if fy and period:
        accounting_period = f"{int(fy):04d}-{int(period):02d}"
    else:
        # Fall back to entry_date month
        d: date = je_row["entry_date"]
        accounting_period = f"{d.year:04d}-{d.month:02d}"

    return JournalEntry(
        entry_id=str(je_row["entry_id"]),
        church_id=church_external,
        fiscal_year=int(fy or je_row["entry_date"].year),
        accounting_period=accounting_period,
        entry_date=je_row["entry_date"],
        reference=str(je_row.get("source_id") or ""),
        vendor_name="",  # not modeled in DB row; lift from source if needed
        description=str(je_row.get("memo") or ""),
        status=JEStatus(_normalize_status_for_model(str(je_row["status"]))),
        lines=lines,
        total_debits=Decimal(str(je_row.get("total_debits") or 0)),
        total_credits=Decimal(str(je_row.get("total_credits") or 0)),
        balanced=bool(je_row.get("is_balanced") or False),
        audit_trail_url=str(je_row.get("audit_trail_url") or ""),
    )


def _normalize_status_for_model(db_status: str) -> str:
    """The DB enum and model JEStatus have partially overlapping names.

    Map DB-only values to model values. Unknown values fall back via the
    JEStatus `_missing_` hook (e.g. PENDING_APPROVAL → OPEN).
    """
    return db_status  # JEStatus._missing_ handles the legacy case.


def _load_lines_for_je(je_pk: int) -> List[JournalEntryLine]:
    rows = execute_query(
        """
        SELECT account_number, fund_id, debit, credit, description, line_no
          FROM journal_entry_lines
         WHERE journal_entry_id = %s
         ORDER BY line_no NULLS LAST, id
        """,
        (je_pk,),
    ) or []
    return [_row_to_line(r) for r in rows]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_journal_entry(church_id: str, je: JournalEntry) -> str:
    """Insert a journal entry and its lines atomically.

    Returns the entry_id.
    """
    church_pk = _resolve_church_pk(church_id)

    # Parse YYYY-MM period to int month if present.
    period_int: Optional[int] = None
    if je.accounting_period and "-" in je.accounting_period:
        try:
            period_int = int(je.accounting_period.split("-", 1)[1])
        except (ValueError, IndexError):
            period_int = None

    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO journal_entries (
                entry_id, church_id, status, entry_date,
                fiscal_year, accounting_period,
                total_debits, total_credits, is_balanced,
                audit_trail_url, memo, version, source, source_id
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            RETURNING id, entry_id
            """,
            (
                je.entry_id,
                church_pk,
                _status_str(je.status),
                je.entry_date,
                je.fiscal_year,
                period_int,
                je.total_debits,
                je.total_credits,
                bool(je.balanced),
                je.audit_trail_url or None,
                je.description or None,
                1,
                "MANUAL",
                je.reference or None,
            ),
        )
        je_pk, entry_id = cur.fetchone()

        # Insert lines
        for line in je.lines:
            cur.execute(
                """
                INSERT INTO journal_entry_lines (
                    journal_entry_id, account_number, fund_id,
                    debit, credit, description, line_no
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                _line_to_row(je_pk, line),
            )
        cur.close()

        # Phase 5a: dual-write a TransactionPosted event per line. The
        # journal_entries / journal_entry_lines rows become projections of
        # these events. Tags carry the CoA/fund/period dimensions.
        _period_tag = je.accounting_period or (
            f"{je.entry_date.year:04d}-{je.entry_date.month:02d}"
        )
        for line in je.lines:
            _ev = FinancialEvent(
                event_type=EventType.TRANSACTION_POSTED,
                church_id=church_id,
                payload={
                    "entry_id": je.entry_id,
                    "line_no": line.sequence,
                    "account_number": line.account_number,
                    "fund_id": line.fund_id,
                    "debit": str(line.debit or 0),
                    "credit": str(line.credit or 0),
                    "memo": line.memo or "",
                    "fiscal_year": je.fiscal_year,
                    "entry_date": je.entry_date.isoformat(),
                    "status": _status_str(je.status),
                    "reference": je.reference or "",
                },
                correlation_id=je.entry_id,
            )
            _ev.add_tag(TagKind.ENTRY, je.entry_id)
            _ev.add_tag(TagKind.ACCOUNT, line.account_number)
            if line.fund_id:
                _ev.add_tag(TagKind.FUND, line.fund_id)
            _ev.add_tag(TagKind.PERIOD, _period_tag)
            emit_event_in_txn(conn, _ev)

    return str(entry_id)


def update_journal_entry(entry_id: str, updates: Dict[str, Any]) -> bool:
    """Update top-level fields of a journal entry with optimistic locking.

    `updates` may include: status, entry_date, posting_date, fiscal_year,
    accounting_period, total_debits, total_credits, is_balanced,
    audit_trail_url, memo, source, source_id, version.

    The current row's version is matched against `updates['version']` if
    provided; otherwise the latest version is read and used. The new row's
    version is `current_version + 1`.

    Returns True on success, False on version mismatch or missing row.
    """
    # Whitelist of updatable columns
    allowed = {
        "status",
        "entry_date",
        "posting_date",
        "fiscal_year",
        "accounting_period",
        "total_debits",
        "total_credits",
        "is_balanced",
        "audit_trail_url",
        "memo",
        "source",
        "source_id",
    }

    expected_version = updates.get("version")
    set_clauses: List[str] = []
    params: List[Any] = []
    for col, val in updates.items():
        if col not in allowed:
            continue
        set_clauses.append(f"{col} = %s")
        if col == "status":
            params.append(_status_str(val))
        else:
            params.append(val)

    if not set_clauses:
        return False

    set_clauses.append("version = version + 1")
    set_clauses.append("updated_at = CURRENT_TIMESTAMP")

    if expected_version is None:
        sql = (
            "UPDATE journal_entries SET "
            + ", ".join(set_clauses)
            + " WHERE entry_id = %s"
        )
        params.append(entry_id)
    else:
        sql = (
            "UPDATE journal_entries SET "
            + ", ".join(set_clauses)
            + " WHERE entry_id = %s AND version = %s"
        )
        params.extend([entry_id, int(expected_version)])

    rowcount = execute_query(sql, tuple(params))
    return bool(rowcount and rowcount > 0)


def get_journal_entry(entry_id: str) -> Optional[JournalEntry]:
    """Load a journal entry with all of its lines.

    Returns None if not found.
    """
    je_row = execute_query(
        """
        SELECT id, entry_id, church_id, status, entry_date, posting_date,
               fiscal_year, accounting_period, total_debits, total_credits,
               is_balanced, audit_trail_url, memo, version, source, source_id
          FROM journal_entries
         WHERE entry_id = %s
        """,
        (entry_id,),
        fetch_one=True,
    )
    if not je_row:
        return None
    lines = _load_lines_for_je(int(je_row["id"]))
    return _row_to_je(je_row, lines)


def list_journal_entries(
    church_id: str,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[JournalEntry]:
    """List journal entries for a church with optional filters."""
    church_pk = _resolve_church_pk(church_id)

    where = ["church_id = %s"]
    params: List[Any] = [church_pk]
    if status is not None:
        where.append("status = %s")
        params.append(_status_str(status))
    if date_from is not None:
        where.append("entry_date >= %s")
        params.append(date_from)
    if date_to is not None:
        where.append("entry_date <= %s")
        params.append(date_to)

    sql = (
        "SELECT id, entry_id, church_id, status, entry_date, posting_date, "
        "       fiscal_year, accounting_period, total_debits, total_credits, "
        "       is_balanced, audit_trail_url, memo, version, source, source_id "
        "  FROM journal_entries "
        " WHERE " + " AND ".join(where) +
        " ORDER BY entry_date DESC, id DESC"
    )
    rows = execute_query(sql, tuple(params)) or []

    out: List[JournalEntry] = []
    for r in rows:
        lines = _load_lines_for_je(int(r["id"]))
        out.append(_row_to_je(r, lines))
    return out


def find_journal_entry(entry_id: str) -> Optional[JournalEntry]:
    """Find a journal entry by entry_id (DB-backed)."""
    return get_journal_entry(entry_id)


def delete_journal_entry(entry_id: str) -> bool:
    """Hard-delete a journal entry. CASCADE removes its lines.

    Returns True if a row was deleted.
    """
    rowcount = execute_query(
        "DELETE FROM journal_entries WHERE entry_id = %s",
        (entry_id,),
    )
    return bool(rowcount and rowcount > 0)


def transition_je_status(entry_id: str, new_status: Any) -> bool:
    """Transition a JE's status, bumping version. Returns True on update."""
    rowcount = execute_query(
        """
        UPDATE journal_entries
           SET status = %s,
               version = version + 1,
               updated_at = CURRENT_TIMESTAMP
         WHERE entry_id = %s
        """,
        (_status_str(new_status), entry_id),
    )
    return bool(rowcount and rowcount > 0)


def je_balance_check(entry_id: str) -> bool:
    """Recompute totals from lines and update is_balanced/total_* on the JE.

    Returns True if the JE is balanced after the recompute.
    """
    je_row = execute_query(
        "SELECT id FROM journal_entries WHERE entry_id = %s",
        (entry_id,),
        fetch_one=True,
    )
    if not je_row:
        return False
    je_pk = int(je_row["id"])

    sums = execute_query(
        """
        SELECT COALESCE(SUM(debit), 0) AS total_debits,
               COALESCE(SUM(credit), 0) AS total_credits
          FROM journal_entry_lines
         WHERE journal_entry_id = %s
        """,
        (je_pk,),
        fetch_one=True,
    ) or {"total_debits": Decimal("0"), "total_credits": Decimal("0")}

    total_debits = Decimal(str(sums["total_debits"] or 0))
    total_credits = Decimal(str(sums["total_credits"] or 0))
    balanced = total_debits == total_credits

    execute_query(
        """
        UPDATE journal_entries
           SET total_debits = %s,
               total_credits = %s,
               is_balanced = %s,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = %s
        """,
        (total_debits, total_credits, balanced, je_pk),
    )
    return balanced
