"""Financial position snapshot.

Single source of truth for the "where do the books stand right now" answer
used by:
  * GET /api/churches/{church_id}/financial-position  (this module)
  * The Books chat assistant (Flow 16) — imports `compute_position()`.
  * The Today dashboard card.

The snapshot is derived from the persisted AccountingContext (funds +
accounts). It's a ledger-balance view, not a closed-period statement;
the response carries confidence labels per field so callers can render
uncertainty honestly.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from ..db import coa_store
from ..db.connection import execute_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/churches", tags=["financial-position"])

_BALANCE_COLUMN_ENSURED = False


def _ensure_balance_column() -> None:
    """Add funds.opening_balance once. Idempotent."""
    global _BALANCE_COLUMN_ENSURED
    if _BALANCE_COLUMN_ENSURED:
        return
    try:
        execute_query(
            "ALTER TABLE funds ADD COLUMN IF NOT EXISTS opening_balance NUMERIC(14, 2) DEFAULT 0"
        )
        _BALANCE_COLUMN_ENSURED = True
    except Exception as e:  # pragma: no cover
        logger.warning("could not ensure funds.opening_balance column: %s", e)


def _fund_balances(church_id: str) -> Dict[str, Dict[str, float]]:
    """Return {fund_id: {opening, je_net, current, je_count}} for a church.

    opening   — funds.opening_balance (seeded)
    je_net    — sum of (credit - debit) across POSTED journal_entry_lines
    current   — opening + je_net (the live ledger balance)
    je_count  — number of posted JE lines that touched this fund

    Sign convention: fund balances are credit-balanced (equity). A credit
    increases the fund; a debit decreases it. Lines without a fund_id are
    skipped — those need a fund tag before they roll into a fund balance.

    Falls back to opening-only if the journal_entries table isn't reachable
    (older schemas, or DB outage).
    """
    _ensure_balance_column()
    try:
        row = execute_query("SELECT id FROM churches WHERE church_id = %s", (church_id,), fetch_one=True)
        if not row:
            return {}
        church_pk = row.get("id") if isinstance(row, dict) else row[0]

        opening_rows = execute_query(
            "SELECT fund_id, COALESCE(opening_balance, 0) AS bal FROM funds WHERE church_id = %s",
            (church_pk,),
        ) or []
        balances: Dict[str, Dict[str, float]] = {
            r["fund_id"]: {
                "opening":  _f(r["bal"]),
                "je_net":   0.0,
                "current":  _f(r["bal"]),
                "je_count": 0,
            }
            for r in opening_rows
        }

        # Roll in posted JE lines. Skip lines with no fund_id — they can't
        # be attributed to a fund balance.
        try:
            je_rows = execute_query(
                """
                SELECT jel.fund_id,
                       COALESCE(SUM(COALESCE(jel.credit, 0) - COALESCE(jel.debit, 0)), 0) AS net,
                       COUNT(*) AS n
                FROM   journal_entry_lines jel
                JOIN   journal_entries je ON je.id = jel.journal_entry_id
                WHERE  je.church_id = %s
                AND    je.status = 'POSTED'
                AND    jel.fund_id IS NOT NULL
                GROUP BY jel.fund_id
                """,
                (church_pk,),
            ) or []
        except Exception as e:  # pragma: no cover — older schema without status/fund_id column
            logger.warning("JE roll-up failed (likely older schema): %s", e)
            je_rows = []

        for jr in je_rows:
            fid = jr.get("fund_id")
            net = _f(jr.get("net"))
            n   = int(jr.get("n") or 0)
            if fid not in balances:
                # JE references a fund that isn't on the funds table — surface
                # it anyway with no opening balance so the user notices.
                balances[fid] = {"opening": 0.0, "je_net": net, "current": net, "je_count": n}
            else:
                balances[fid]["je_net"]   = net
                balances[fid]["current"]  = balances[fid]["opening"] + net
                balances[fid]["je_count"] = n

        return balances
    except Exception as e:  # pragma: no cover
        logger.warning("fund balances lookup failed: %s", e)
        return {}


def _f(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def compute_position(church_id: str) -> Optional[Dict[str, Any]]:
    """Return a structured financial-position snapshot, or None if unknown church.

    Shape:
        {
          "church_id": str,
          "as_of": ISO8601,
          "basis": "ledger_balance",
          "totals": {
            "total_fund_balance": float,
            "unrestricted": float,
            "temporarily_restricted": float,
            "permanently_restricted": float,
          },
          "funds": [
             {fund_id, fund_name, restriction_class, current_balance, share_pct},
             ...
          ],
          "confidence": {
            "fund_level": "HIGH",
            "gl_rollup":  "MEDIUM",
            "as_of_basis": "ledger snapshot, not a closed-period statement",
          }
        }
    """
    try:
        ctx = coa_store.load_accounting_context(church_id)
    except ValueError:
        return None
    except Exception as e:  # pragma: no cover
        logger.exception("financial-position load failed: %s", e)
        return None

    funds = list(getattr(ctx, "funds", []) or [])
    out_funds: List[Dict[str, Any]] = []
    total = 0.0
    by_class = {
        "WITHOUT_RESTRICTION": 0.0,
        "WITH_RESTRICTION_PURPOSE": 0.0,
        "WITH_RESTRICTION_PERMANENT": 0.0,
    }

    # Live balances from SQL — overrides the AccountingContext default of 0.
    # Shape: {fund_id: {opening, je_net, current, je_count}}.
    live_balances = _fund_balances(church_id)
    total_je_count = 0
    total_je_net = 0.0

    def _enum_str(v: Any) -> str:
        """Render an enum cleanly: 'WITH_RESTRICTION_PURPOSE' not 'RESTRICTIONCLASS.WITH_RESTRICTION_PURPOSE'."""
        s = str(v or "")
        return s.split(".")[-1].upper() if "." in s else s.upper()

    for f in funds:
        fund_id = getattr(f, "fund_id", None)
        seed_bal = _f(getattr(f, "current_balance", None))
        live = live_balances.get(fund_id) or {}
        if live:
            bal = live.get("current", seed_bal)
            je_net = live.get("je_net", 0.0)
            je_n   = live.get("je_count", 0)
            opening = live.get("opening", seed_bal)
        else:
            bal, je_net, je_n, opening = seed_bal, 0.0, 0, seed_bal
        rc = _enum_str(getattr(f, "restriction_class", ""))
        out_funds.append({
            "fund_id":           fund_id,
            "fund_name":         getattr(f, "fund_name", None),
            "fund_category":     _enum_str(getattr(f, "fund_category", "")),
            "restriction_class": rc,
            "opening_balance":   round(opening, 2),
            "je_net":            round(je_net, 2),
            "posted_je_count":   je_n,
            "current_balance":   round(bal, 2),
        })
        total += bal
        total_je_count += je_n
        total_je_net += je_net
        if rc in by_class:
            by_class[rc] += bal

    # Compute share_pct after we have the total so the UI can render a stacked bar.
    for row in out_funds:
        row["share_pct"] = (row["current_balance"] / total * 100.0) if total else 0.0

    # Sort largest fund first — the UI typically wants the biggest line at the top.
    out_funds.sort(key=lambda r: r["current_balance"], reverse=True)

    # If posted JEs touched any fund this period, the GL roll-up rises from
    # MEDIUM (seed-only) to HIGH (actual postings reflected).
    gl_confidence = "HIGH" if total_je_count > 0 else "MEDIUM"

    return {
        "church_id": church_id,
        "as_of": datetime.utcnow().isoformat(),
        "basis": "ledger_balance",
        "fiscal_year": getattr(ctx, "fiscal_year", None),
        "totals": {
            "total_fund_balance":     round(total, 2),
            "unrestricted":           round(by_class["WITHOUT_RESTRICTION"], 2),
            "temporarily_restricted": round(by_class["WITH_RESTRICTION_PURPOSE"], 2),
            "permanently_restricted": round(by_class["WITH_RESTRICTION_PERMANENT"], 2),
            "posted_je_net":          round(total_je_net, 2),
            "posted_je_count":        total_je_count,
        },
        "funds": out_funds,
        "confidence": {
            "fund_level":   "HIGH",
            "gl_rollup":    gl_confidence,
            "as_of_basis":  (
                "live ledger — posted JEs rolled in"
                if total_je_count > 0
                else "ledger snapshot, not a closed-period statement"
            ),
        },
    }


@router.get("/{church_id}/financial-position")
async def get_financial_position(church_id: str) -> Dict[str, Any]:
    snap = compute_position(church_id)
    if snap is None:
        return {"church_id": church_id, "ok": False, "error": "unknown church"}
    snap["ok"] = True
    return snap
