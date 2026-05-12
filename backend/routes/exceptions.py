"""Phase 5: Exceptions Queue action endpoints.

Endpoints:
  GET /api/churches/{church_id}/exceptions        — list exceptions for a church
  POST /api/exceptions/{id}/resolve   — mark resolved, no further action
  POST /api/exceptions/{id}/approve   — approve, write DECISION_PACKET verdict=APPROVED
  POST /api/exceptions/{id}/reject    — reject, write DECISION_PACKET verdict=REJECTED
  POST /api/exceptions/{id}/route     — route to another principal (emits HITL_ESCALATION)

Card resolution path needs church scoping; church_id is supplied via query
or body (defaults to env EMBARK_DEFAULT_CHURCH or "holy_comforter").
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from ..db import card_store
from ..tools import exception_store
from ..membrane.emitters import emit_hitl_escalation

# Router for listing exceptions by church
church_router = APIRouter(prefix="/api/churches", tags=["exceptions-queue"])

# Router for exception actions
action_router = APIRouter(prefix="/api/exceptions", tags=["exceptions-queue"])

_DEFAULT_CHURCH = os.environ.get("EMBARK_DEFAULT_CHURCH", "holy_comforter")


def _resolve_church(body: Optional[Dict[str, Any]], church_id: Optional[str]) -> str:
    if church_id:
        return church_id
    if body and body.get("church_id"):
        return str(body["church_id"])
    return _DEFAULT_CHURCH


# GET endpoint to list exceptions for a church
@church_router.get("/{church_id}/exceptions")
async def list_exceptions(
    church_id: str,
    include_resolved: bool = Query(default=False),
    include_synthetic: bool = Query(default=False),
) -> Dict[str, Any]:
    """List exception cards for a church.

    By default hides RESOLVED items and `(synthetic)` test cards (which were
    historically generated when /resolve was called against an unknown ID).
    """
    try:
        cards, total = card_store.list_exception_cards(church_id, limit=200)
        filtered = []
        for c in cards:
            status = (c.get("status") or "").upper()
            title  = c.get("title") or ""
            if not include_resolved and status in ("RESOLVED", "CANCELLED"):
                continue
            if not include_synthetic and title.startswith("(synthetic)"):
                continue
            filtered.append(c)
        return {
            "church_id": church_id,
            "cards": filtered,
            "total": len(filtered),
            "raw_total": total,
            "count": len(filtered),
            "ok": True,
        }
    except Exception as e:
        return {
            "church_id": church_id,
            "cards": [],
            "total": 0,
            "count": 0,
            "ok": False,
            "error": str(e),
        }


# POST endpoints for exception actions
@action_router.post("/{exception_id}/resolve")
async def resolve_exception(
    exception_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    church_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    ch = _resolve_church(body, church_id)
    rec = exception_store.update_exception(ch, exception_id, status="RESOLVED")
    if rec is None:
        # No stub creation — just report the no-op. Earlier behaviour was to
        # synthesize a "(synthetic) {id}" exception card so the response could
        # be 200, but that leaked test data into the user-visible queue.
        return {"ok": True, "card_id": exception_id, "status": "RESOLVED", "no_op": True}
    return {"ok": True, "card_id": exception_id, "status": "RESOLVED"}


@action_router.post("/{exception_id}/approve")
async def approve_exception(
    exception_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    church_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    ch = _resolve_church(body, church_id)
    actor = (body or {}).get("actor", "unknown")
    reasoning = (body or {}).get("reasoning")
    packet = exception_store.write_decision(
        ch, exception_id, verdict="APPROVED", actor=actor, reasoning=reasoning,
    )
    return {"ok": True, "card_id": exception_id, "verdict": "APPROVED", "packet": packet}


@action_router.post("/{exception_id}/reject")
async def reject_exception(
    exception_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    church_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    ch = _resolve_church(body, church_id)
    actor = (body or {}).get("actor", "unknown")
    reasoning = (body or {}).get("reasoning")
    packet = exception_store.write_decision(
        ch, exception_id, verdict="REJECTED", actor=actor, reasoning=reasoning,
    )
    return {"ok": True, "card_id": exception_id, "verdict": "REJECTED", "packet": packet}


@action_router.post("/{exception_id}/route")
async def route_exception(
    exception_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    church_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    body = body or {}
    ch = _resolve_church(body, church_id)
    new_principal = body.get("principal") or body.get("to")
    if not new_principal:
        raise HTTPException(status_code=400, detail="missing 'principal' in body")
    actor = body.get("actor", "unknown")
    reason = body.get("reason", "route")

    rec = exception_store.update_exception(
        ch, exception_id, principal=new_principal, status="IN_REVIEW"
    )
    if rec is None:
        rec = exception_store.create_exception(
            ch, title=f"(routed) {exception_id}",
            description=reason, principal=new_principal,
        )

    # Membrane Phase 5: HITL_ESCALATION (signal 67)
    try:
        emit_hitl_escalation(
            item_id=exception_id,
            escalation_reason=reason,
            escalated_by=actor,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "card_id": exception_id,
        "principal": new_principal,
        "status": "IN_REVIEW",
    }


# Export both routers
router = action_router  # Default export for backward compatibility
