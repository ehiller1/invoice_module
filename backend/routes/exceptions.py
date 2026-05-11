"""Phase 5: Exceptions Queue action endpoints.

Endpoints:
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

from ..tools import exception_store
from ..membrane.emitters import emit_hitl_escalation

router = APIRouter(prefix="/api/exceptions", tags=["exceptions-queue"])

_DEFAULT_CHURCH = os.environ.get("EMBARK_DEFAULT_CHURCH", "holy_comforter")


def _resolve_church(body: Optional[Dict[str, Any]], church_id: Optional[str]) -> str:
    if church_id:
        return church_id
    if body and body.get("church_id"):
        return str(body["church_id"])
    return _DEFAULT_CHURCH


@router.post("/{exception_id}/resolve")
async def resolve_exception(
    exception_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    church_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    ch = _resolve_church(body, church_id)
    rec = exception_store.update_exception(ch, exception_id, status="RESOLVED")
    if rec is None:
        # Allow resolve on unseen IDs (idempotent stub).
        rec = exception_store.create_exception(
            ch, title=f"(synthetic) {exception_id}",
            description="resolved via API",
        )
        exception_store.update_exception(ch, rec["card_id"], status="RESOLVED")
    return {"ok": True, "card_id": exception_id, "status": "RESOLVED"}


@router.post("/{exception_id}/approve")
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


@router.post("/{exception_id}/reject")
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


@router.post("/{exception_id}/route")
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
