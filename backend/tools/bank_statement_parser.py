"""Parse bank statements in CSV / OFX / QFX format (FR-07.1)."""
from __future__ import annotations
import csv
import hashlib
import io
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from backend.models.schemas import BankTransaction


def parse_statement(file_bytes: bytes, filename: str) -> List[BankTransaction]:
    """Auto-detect format from filename extension and parse."""
    name_lower = (filename or "").lower()
    if name_lower.endswith(".ofx") or name_lower.endswith(".qfx"):
        return parse_ofx(file_bytes, filename)
    if name_lower.endswith(".csv"):
        return parse_csv(file_bytes, filename)
    # Try OFX first (more strict format), fall back to CSV.
    try:
        return parse_ofx(file_bytes, filename)
    except Exception:
        return parse_csv(file_bytes, filename)


def parse_csv(file_bytes: bytes, filename: str) -> List[BankTransaction]:
    """Parse CSV with auto-detected column mapping."""
    text = file_bytes.decode("utf-8", errors="replace")
    # Strip BOM if present.
    if text.startswith("﻿"):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text))

    DATE_COLS = ["date", "transaction date", "post date", "posted date"]
    DESC_COLS = ["description", "memo", "details", "transaction", "name", "merchant"]
    AMOUNT_COLS = ["amount", "transaction amount"]
    TYPE_COLS = ["type", "transaction type"]

    txns: List[BankTransaction] = []
    for idx, row in enumerate(reader):
        if not row:
            continue
        # Lowercase keys for matching
        rl = {(k or "").lower().strip(): (v if v is not None else "") for k, v in row.items() if k is not None}

        # Find date
        d: Optional[date] = None
        for c in DATE_COLS:
            if c in rl and rl[c]:
                d = _parse_date(rl[c])
                if d:
                    break
        if not d:
            continue

        # Find amount (signed)
        amount: Optional[Decimal] = None
        for c in AMOUNT_COLS:
            if c in rl and rl[c]:
                amount = _decimal_or_none(rl[c])
                if amount is not None:
                    break
        if amount is None:
            # Try debit/credit columns
            debit = _decimal_or_none(
                rl.get("debit") or rl.get("withdrawal") or rl.get("debits")
            )
            credit = _decimal_or_none(
                rl.get("credit") or rl.get("deposit") or rl.get("credits")
            )
            if debit is not None and debit != Decimal("0"):
                amount = -abs(debit)
            elif credit is not None and credit != Decimal("0"):
                amount = abs(credit)
        if amount is None:
            continue

        # Description
        desc = ""
        for c in DESC_COLS:
            if c in rl and rl[c]:
                desc = str(rl[c]).strip()
                break

        # Type
        tx_type = "CREDIT" if amount > 0 else "DEBIT"
        for c in TYPE_COLS:
            if c in rl and rl[c]:
                tx_type = str(rl[c]).strip().upper()
                break

        # Generate stable id
        tid_src = f"{d.isoformat()}|{amount}|{desc}|{idx}"
        txn_id = hashlib.md5(tid_src.encode()).hexdigest()[:16]

        txns.append(
            BankTransaction(
                txn_id=txn_id,
                date=d,
                description=desc,
                amount=amount,
                type=tx_type,
                raw=dict(row),
                source_filename=filename,
            )
        )

    return txns


def _parse_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _decimal_or_none(s) -> Optional[Decimal]:
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    try:
        return Decimal(t.replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def parse_ofx(file_bytes: bytes, filename: str) -> List[BankTransaction]:
    """Parse OFX/QFX file. Requires `ofxparse`."""
    try:
        from ofxparse import OfxParser  # type: ignore
    except ImportError as exc:
        raise RuntimeError("ofxparse not installed; cannot parse OFX/QFX") from exc

    fp = io.BytesIO(file_bytes)
    ofx = OfxParser.parse(fp)
    txns: List[BankTransaction] = []
    for account in getattr(ofx, "accounts", []) or []:
        statement = getattr(account, "statement", None)
        if not statement:
            continue
        for t in getattr(statement, "transactions", []) or []:
            raw_tdate = getattr(t, "date", None)
            tdate: date
            if isinstance(raw_tdate, datetime):
                tdate = raw_tdate.date()
            elif isinstance(raw_tdate, date):
                tdate = raw_tdate
            else:
                tdate = date.today()
            payee = getattr(t, "payee", "") or ""
            memo = getattr(t, "memo", "") or ""
            amt = Decimal(str(getattr(t, "amount", 0)))
            tid = (
                getattr(t, "id", None)
                or hashlib.md5(f"{tdate}|{amt}|{payee}".encode()).hexdigest()[:16]
            )
            tx_type = (getattr(t, "type", None) or ("CREDIT" if amt > 0 else "DEBIT")).upper()
            txns.append(
                BankTransaction(
                    txn_id=tid,
                    date=tdate or date.today(),
                    description=payee or memo,
                    amount=amt,
                    type=tx_type,
                    raw={"checknum": getattr(t, "checknum", None), "memo": memo},
                    source_filename=filename,
                )
            )
    return txns
