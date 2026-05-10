"""Structural matcher (Phase 5c).

The vision says reconciliation is *structural*, not a process. Instead of
a destination page where a human clicks "Auto-Match" on a schedule, the
matcher runs continuously: every time a `BankItemObserved` event is
recorded, the matcher tries to pair it with an existing journal entry
that represents the same underlying economic event.

What "structural agreement" means here:
  amount diff < 0.01 USD AND date diff <= 3 days AND JE.status = BALANCED

The matcher reuses the SQL range-join in `recon_store.find_matching_entries`
so the Phase 4 algorithm is preserved. What changes is *when* it runs:
synchronously after every Plaid sync, with no human in the loop. The
remaining items become the canonical "exceptions" inbox.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..db import plaid_store, recon_store
from ..db.connection import execute_query
from .emitter import emit_event
from .schemas import EventType, FinancialEvent, TagKind


def run_for_church(
    church_id: str,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the structural matcher across all unmatched Plaid items.

    Returns a report:
        {
          "matched": int,    # how many new matches were made this run
          "exceptions": int, # how many txns remain unmatched after this run
          "total": int,      # total Plaid txns considered
          "ran_at": "...",
        }

    Side effects:
      - inserts rows into recon_matches for new matches
      - emits StructuralMatchObserved events for each new match
    """
    txns = plaid_store.load_plaid_transactions(church_id, account_id=account_id)

    existing = recon_store.load_matches(church_id)
    matched_ids = set(existing.keys())

    church_pk = recon_store._resolve_church_pk(church_id)
    pk_rows = execute_query(
        """
        SELECT pt.id AS pk, pt.txn_id AS txn_id
          FROM plaid_transactions pt
         WHERE pt.church_id = %s
        """,
        (church_pk,),
    ) or []
    pk_by_external: Dict[str, int] = {r["txn_id"]: int(r["pk"]) for r in pk_rows}

    newly_matched = 0
    for txn in txns:
        if txn.txn_id in matched_ids:
            continue
        candidates = recon_store.find_matching_entries(church_id, txn)
        if not candidates:
            continue
        best = candidates[0]
        plaid_pk = pk_by_external.get(txn.txn_id)
        if plaid_pk is None:
            continue
        recon_store.save_match(
            church_id=church_id,
            plaid_txn_id=plaid_pk,
            journal_entry_id=int(best["je_id"]),
            amount_diff=best.get("amount_diff"),
            days_diff=int(best["days_diff"]) if best.get("days_diff") is not None else None,
        )
        matched_ids.add(txn.txn_id)
        newly_matched += 1

        # Emit a StructuralMatchObserved event so the match itself is
        # auditable in the event log alongside the recon_matches row.
        try:
            ev = FinancialEvent(
                event_type=EventType.STRUCTURAL_MATCH,
                church_id=church_id,
                payload={
                    "plaid_txn_id": txn.txn_id,
                    "plaid_txn_pk": plaid_pk,
                    "journal_entry_pk": int(best["je_id"]),
                    "entry_id": best.get("entry_id"),
                    "amount_diff": str(best.get("amount_diff") or 0),
                    "days_diff": int(best["days_diff"]) if best.get("days_diff") is not None else None,
                    "matcher": "structural_v1",
                },
                correlation_id=str(best.get("entry_id") or txn.txn_id),
            )
            if best.get("entry_id"):
                ev.add_tag(TagKind.ENTRY, str(best["entry_id"]))
            emit_event(ev)
        except Exception:
            pass

    total_matched_after = sum(1 for t in txns if t.txn_id in matched_ids)
    exceptions = len(txns) - total_matched_after

    return {
        "matched": total_matched_after,
        "newly_matched": newly_matched,
        "exceptions": exceptions,
        "total": len(txns),
        "ran_at": datetime.utcnow().isoformat(),
    }


def list_exceptions(church_id: str) -> List[Dict[str, Any]]:
    """Return the unmatched-Plaid-txn list shaped for the exceptions inbox.

    This is the canonical inbox surface: items the structural matcher could
    not pair against a balanced journal entry within tolerance. The frontend
    surfaces them on `exceptions-queue.html`; the old reconciliation
    destination page is deprecated.
    """
    txns = recon_store.list_unmatched_txns(church_id)
    out: List[Dict[str, Any]] = []
    for t in txns:
        out.append({
            "kind": "plaid_unmatched",
            "txn_id": t.txn_id,
            "date": t.date.isoformat() if t.date else None,
            "amount": str(t.amount or 0),
            "description": t.description or "",
            "merchant_name": t.merchant_name or "",
            "category": t.category or "",
        })
    return out
