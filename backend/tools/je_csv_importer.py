"""Batch CSV importer for journal entries (Phase 3.8 / FR-08-recurring).

Parses a CSV with the columns

    memo, from_account, to_account, amount, fund [, date]

and produces one DRAFT ``JournalEntry`` per row. Rows that fail validation
are skipped and reported in the returned ``ImportResult``. The COA + funds
of the church (if available) are used to validate account / fund codes; if
no COA is on file, validation falls back to a simple shape check so the
endpoint is still usable in dev/test churches.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set

from ..models.schemas import JEStatus, JournalEntry, JournalEntryLine

logger = logging.getLogger("eime.je_csv_importer")

REQUIRED_COLUMNS = ("memo", "from_account", "to_account", "amount", "fund")


@dataclass
class ImportResult:
    drafted_count: int = 0
    failed_count: int = 0
    drafted_ids: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "drafted_count": self.drafted_count,
            "failed_count": self.failed_count,
            "drafted": self.drafted_ids,
            "errors": self.errors,
        }


def _load_coa_codes(church_id: str) -> tuple[Optional[Set[str]], Optional[Set[str]]]:
    """Return (account_codes, fund_codes) for validation. ``None`` means
    no COA found (skip validation)."""
    try:
        from .coa_store import load_accounting_context
    except Exception:  # pragma: no cover
        return None, None
    try:
        ctx = load_accounting_context(church_id)
    except Exception:
        return None, None
    if ctx is None:
        return None, None
    accounts: Set[str] = set()
    for a in getattr(ctx, "accounts", []) or []:
        for k in ("account_number", "code", "number"):
            v = getattr(a, k, None) if not isinstance(a, dict) else a.get(k)
            if v:
                accounts.add(str(v))
                break
    funds: Set[str] = set()
    for f in getattr(ctx, "funds", []) or []:
        for k in ("fund_id", "code", "id"):
            v = getattr(f, k, None) if not isinstance(f, dict) else f.get(k)
            if v:
                funds.add(str(v))
                break
    return (accounts or None), (funds or None)


def _parse_amount(raw: Any) -> Decimal:
    s = str(raw or "").replace("$", "").replace(",", "").strip()
    if not s:
        raise ValueError("amount is required")
    try:
        amt = Decimal(s)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"amount must be a positive number (got '{raw}')") from e
    if amt <= 0:
        raise ValueError(f"amount must be positive (got {amt})")
    return amt


def _parse_date(raw: Any) -> date:
    s = str(raw or "").strip()
    if not s:
        return datetime.utcnow().date()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"date must be YYYY-MM-DD (got '{raw}')") from e


def _row_to_je(
    row: dict,
    row_num: int,
    church_id: str,
    accounts: Optional[Set[str]],
    funds: Optional[Set[str]],
) -> JournalEntry:
    from_acct = (row.get("from_account") or "").strip()
    to_acct = (row.get("to_account") or "").strip()
    memo = (row.get("memo") or "").strip()
    fund = (row.get("fund") or "GEN").strip() or "GEN"

    if not from_acct:
        raise ValueError("from_account is required")
    if not to_acct:
        raise ValueError("to_account is required")

    amt = _parse_amount(row.get("amount"))
    entry_date = _parse_date(row.get("date"))

    if accounts is not None:
        if from_acct not in accounts:
            raise ValueError(f"GL code {from_acct} not in COA")
        if to_acct not in accounts:
            raise ValueError(f"GL code {to_acct} not in COA")
    if funds is not None and fund not in funds:
        raise ValueError(f"fund {fund} not configured")

    now = datetime.utcnow()
    eid = f"CSV-{now.strftime('%Y%m%d%H%M%S%f')}-{row_num}"
    return JournalEntry(
        entry_id=eid,
        church_id=church_id,
        fiscal_year=entry_date.year,
        accounting_period=entry_date.strftime("%Y-%m"),
        entry_date=entry_date,
        reference=f"csv-row-{row_num}",
        vendor_name=memo or f"CSV row {row_num}",
        description=memo or f"CSV import row {row_num}",
        status=JEStatus.DRAFT,
        lines=[
            JournalEntryLine(
                sequence=1, account_number=from_acct, account_name=from_acct,
                fund_id=fund, fund_name=fund,
                debit=amt, credit=Decimal("0"), memo=memo,
            ),
            JournalEntryLine(
                sequence=2, account_number=to_acct, account_name=to_acct,
                fund_id=fund, fund_name=fund,
                debit=Decimal("0"), credit=amt, memo=memo,
            ),
        ],
        total_debits=amt,
        total_credits=amt,
        balanced=True,
    )


def parse_je_csv(
    file_bytes: bytes,
    church_id: str,
) -> tuple[List[JournalEntry], ImportResult]:
    """Parse the CSV and return (jes, result). Caller is responsible for
    persistence; ``result`` already contains drafted_ids + errors."""
    text = file_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    result = ImportResult()
    if reader.fieldnames is None:
        result.errors.append("CSV is empty or has no header row")
        result.failed_count = 1
        return [], result
    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        for col in missing:
            result.errors.append(f"CSV missing required column '{col}'")
        result.failed_count = len(missing)
        return [], result

    accounts, funds = _load_coa_codes(church_id)

    jes: List[JournalEntry] = []
    for idx, row in enumerate(reader, start=2):  # row 1 is header
        try:
            je = _row_to_je(row, idx, church_id, accounts, funds)
            jes.append(je)
            result.drafted_ids.append(je.entry_id)
            result.drafted_count += 1
        except Exception as e:
            result.failed_count += 1
            result.errors.append(f"Row {idx}: {e}")
    return jes, result


def _persist_je(church_id: str, je: JournalEntry, data_dir: Optional[Path] = None) -> None:
    """Append a JE to the church's jes_*.jsonl file."""
    base = data_dir or (Path(__file__).resolve().parent.parent / "data")
    base.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in church_id if c.isalnum() or c in "_-") or "default"
    path = base / f"jes_{safe}.jsonl"
    import json as _json
    with path.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(je.model_dump(), default=str) + "\n")


def import_je_csv(
    file_bytes: bytes,
    church_id: str,
    created_by: Optional[str] = None,
    data_dir: Optional[Path] = None,
) -> ImportResult:
    """Parse a CSV, persist each valid row as a DRAFT JE, return a summary."""
    jes, result = parse_je_csv(file_bytes, church_id)
    for je in jes:
        try:
            _persist_je(church_id, je, data_dir=data_dir)
        except Exception as e:  # pragma: no cover - filesystem failure
            logger.warning(f"Failed to persist {je.entry_id}: {e}")
            result.failed_count += 1
            result.drafted_count -= 1
            result.errors.append(f"Persist {je.entry_id}: {e}")
    return result
