"""Phase 5: Recommendations Queue (NBA - Next Best Action) endpoints.

Endpoints:
  GET  /api/churches/{church_id}/recommendations  — list recommendation cards for a church
  POST /api/recommendations-session/{id}/accept   — accept a recommendation (session-auth)
  POST /api/recommendations-session/{id}/decline  — decline a recommendation (session-auth)
  POST /api/recommendations-session/{id}/defer    — defer a recommendation (session-auth)

Listing endpoint enriches each card with `cash_impact_usd` and a confidence
bucket so the frontend never has to display the raw `impact_score` to users.

Session-auth action endpoints accept identity via X-Voter-Id / X-User-Role
headers (set by the EIMESession frontend helper), avoiding the bearer-token
requirement of the legacy /api/recommendations/{id}/* routes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Body, Header, HTTPException, Query

from ..db import card_store
from ..db.connection import execute_query

logger = logging.getLogger(__name__)

router         = APIRouter(prefix="/api/churches",                tags=["recommendations-queue"])
action_router  = APIRouter(prefix="/api/recommendations-session", tags=["recommendations-queue"])


# ──────────────────────────────────────────────────────────────────────────
# Cash-impact derivation
#
# Different recommendation types compute $ impact differently. When a
# recommender hasn't populated `evidence.cash_impact_usd` directly, we fall
# back to a per-type heuristic so the UI doesn't show "impact score 3.50".
# ──────────────────────────────────────────────────────────────────────────

def _normalize_pct(raw: Any) -> float:
    """Accept 0–1 fractions or 0–100 percentages."""
    try:
        x = float(raw or 0)
    except (TypeError, ValueError):
        return 0.0
    if x <= 1.0:
        x *= 100.0
    return max(0.0, min(100.0, x))


def _vendor_txn_sample(church_id: str, vendor_hint: Optional[str]) -> Tuple[float, int]:
    """Return (avg_amount, txn_count) for a vendor hint. Best-effort SQL probe."""
    if not vendor_hint:
        return (0.0, 0)
    try:
        result = execute_query(
            """
            SELECT COALESCE(AVG(total_amount), 0) AS avg_amt,
                   COUNT(*)                      AS n
            FROM   processing_jobs pj
            JOIN   churches c ON c.id = pj.church_id
            WHERE  c.church_id = %s
            AND    vendor ILIKE %s
            AND    total_amount IS NOT NULL
            """,
            (church_id, f"%{vendor_hint}%"),
            fetch_one=True,
        )
        if not result:
            return (0.0, 0)
        # fetch_one=True returns a single dict; defensive cast for static checkers.
        row: Dict[str, Any] = result if isinstance(result, dict) else (result[0] if result else {})
        return (float(row.get("avg_amt") or 0.0), int(row.get("n") or 0))
    except Exception:
        return (0.0, 0)


def _derive_cash_impact(card: Dict[str, Any], church_id: str) -> float:
    """Return an estimated dollar impact for a recommendation card.

    Order of preference:
      1. `evidence.cash_impact_usd` if the recommender filled it in
      2. Per-recommendation-type heuristic
      3. Fall back to 0.0 (UI then renders 'Not yet modelled')
    """
    ev = card.get("evidence") or {}
    if ev.get("cash_impact_usd") is not None:
        try:
            return float(ev["cash_impact_usd"])
        except (TypeError, ValueError):
            pass

    rtype = (card.get("recommendation_type") or "").lower()
    confidence = _normalize_pct(card.get("confidence_pct"))
    confidence_w = confidence / 100.0 if confidence else 0.0

    title = (card.get("title") or "")
    descr = (card.get("description") or "")
    text = f"{title} {descr}"

    # Try to pull a vendor name from the title for vendor-typed recommendations.
    vendor_hint = None
    if "vendor" in rtype:
        words = title.replace("Reclassify vendor", "").replace("Move", "").split()
        vendor_hint = " ".join(words[:2]).strip() if words else None

    if rtype in ("vendor_reclassification", "vendor_classification"):
        avg_amt, n = _vendor_txn_sample(church_id, vendor_hint)
        # If we can sample real txns, project a year of misclassified dollars.
        if avg_amt > 0 and n > 0:
            return round(avg_amt * max(n, 1) * confidence_w, 2)
        # Otherwise default: $200/txn × 12 (one txn/month) × confidence.
        return round(200.0 * 12 * confidence_w, 2)

    if rtype in ("fund_reallocation", "fund_rebalance"):
        # Look for "$NNK" or "$NN,NNN" tokens in description.
        import re
        m = re.search(r"\$([\d,]+)\s*[kK]\b", text)
        if m:
            return float(m.group(1).replace(",", "")) * 1000.0
        m = re.search(r"\$([\d,]+(?:\.\d+)?)", text)
        if m:
            return float(m.group(1).replace(",", ""))

    if rtype in ("policy_change", "expense_control", "cost_reduction"):
        return round(5000.0 * confidence_w, 2)

    return 0.0


def _confidence_bucket(pct: float) -> str:
    if pct >= 80:
        return "high"
    if pct >= 60:
        return "medium"
    if pct > 0:
        return "low"
    return "unknown"


def _enrich(card: Dict[str, Any], church_id: str) -> Dict[str, Any]:
    ev = dict(card.get("evidence") or {})
    cash = _derive_cash_impact(card, church_id)
    confidence = _normalize_pct(card.get("confidence_pct"))
    ev["cash_impact_usd"] = cash
    ev["cash_impact_basis"] = "modeled" if (card.get("evidence") or {}).get("cash_impact_usd") is not None else "estimated"
    ev["confidence_pct"]    = confidence
    ev["confidence_bucket"] = _confidence_bucket(confidence)
    card["evidence"] = ev
    return card


@router.get("/{church_id}/recommendations")
async def list_recommendations(church_id: str) -> Dict[str, Any]:
    """List recommendation cards for a church, enriched with $ impact."""
    try:
        cards, total = card_store.list_recommendation_cards(church_id, limit=100)
        cards = [_enrich(c, church_id) for c in cards]
        return {
            "church_id": church_id,
            "cards": cards,
            "total": total,
            "count": len(cards),
            "ok": True,
        }
    except Exception as e:
        logger.exception("list_recommendations failed")
        return {
            "church_id": church_id,
            "cards": [],
            "total": 0,
            "count": 0,
            "ok": False,
            "error": str(e),
        }


# ──────────────────────────────────────────────────────────────────────────
# Session-auth action endpoints
# ──────────────────────────────────────────────────────────────────────────

def _require_user(x_voter_id: Optional[str]) -> str:
    if not x_voter_id or x_voter_id == "guest":
        raise HTTPException(
            status_code=401,
            detail="Sign in (switch user from the sidebar chip) before deciding on a suggestion.",
        )
    return x_voter_id


def _update_card_status(card_id: str, status: str, decision_data: Dict[str, Any]) -> bool:
    """Update a recommendation card status + decision_data. Returns True if a row was updated."""
    result = execute_query(
        """
        UPDATE recommendation_cards
        SET status = %s,
            decided_at = NOW(),
            decision_data = COALESCE(decision_data, '{}'::jsonb) || %s::jsonb
        WHERE card_id = %s
        """,
        (status, json.dumps(decision_data), card_id),
    )
    return bool(result)


@action_router.post("/{recommendation_id}/accept")
async def accept_recommendation(
    recommendation_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    x_voter_id: Optional[str] = Header(default=None, alias="X-Voter-Id"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
) -> Dict[str, Any]:
    voter = _require_user(x_voter_id)
    body = body or {}
    payload = {
        "decision": "accepted",
        "decided_by": voter,
        "decided_role": x_user_role,
        "decided_at": datetime.utcnow().isoformat(),
        "notes": body.get("notes"),
    }
    _update_card_status(recommendation_id, "RESOLVED", payload)
    logger.info("recommendation %s accepted by %s", recommendation_id, voter)
    return {"ok": True, "recommendation_id": recommendation_id, "status": "accepted", "decided_by": voter}


@action_router.post("/{recommendation_id}/decline")
async def decline_recommendation(
    recommendation_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    x_voter_id: Optional[str] = Header(default=None, alias="X-Voter-Id"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
) -> Dict[str, Any]:
    voter = _require_user(x_voter_id)
    body = body or {}
    payload = {
        "decision": "declined",
        "decided_by": voter,
        "decided_role": x_user_role,
        "decided_at": datetime.utcnow().isoformat(),
        "reason": body.get("reason"),
    }
    _update_card_status(recommendation_id, "CANCELLED", payload)
    logger.info("recommendation %s declined by %s", recommendation_id, voter)
    return {"ok": True, "recommendation_id": recommendation_id, "status": "declined", "decided_by": voter}


@action_router.post("/{recommendation_id}/defer")
async def defer_recommendation(
    recommendation_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    x_voter_id: Optional[str] = Header(default=None, alias="X-Voter-Id"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
) -> Dict[str, Any]:
    """Defer the recommendation. Default horizon is 30 days; body.defer_days overrides."""
    voter = _require_user(x_voter_id)
    body = body or {}
    try:
        days = int(body.get("defer_days") or 30)
    except (TypeError, ValueError):
        days = 30
    defer_until = (datetime.utcnow() + timedelta(days=max(days, 1))).isoformat()
    payload = {
        "decision": "deferred",
        "deferred_by": voter,
        "deferred_role": x_user_role,
        "deferred_at": datetime.utcnow().isoformat(),
        "defer_until": defer_until,
        "defer_days": days,
        "reason": body.get("reason"),
    }
    # Defer keeps the card in IN_REVIEW (not RESOLVED) so it can come back.
    _update_card_status(recommendation_id, "IN_REVIEW", payload)
    logger.info("recommendation %s deferred %sd by %s", recommendation_id, days, voter)
    return {
        "ok": True,
        "recommendation_id": recommendation_id,
        "status": "deferred",
        "defer_until": defer_until,
        "defer_days": days,
        "deferred_by": voter,
    }
