"""Phase 5: Policies Queue action endpoints.

POST /api/policies/{id}/vote
  Body: {voter_id?, value|vote: "approve"|"reject"|"abstain", rationale?, church_id?}
  Routes through the membrane policy_management module (canonical store).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..db import card_store
from fastapi import APIRouter, Body, HTTPException, Query

from ..membrane.pledge.policy_management import vote_on_policy as _vote_on_policy

church_router = APIRouter(prefix="/api/churches", tags=["policies-queue"])
action_router = APIRouter(prefix="/api/policies", tags=["policies-queue"])


@church_router.get("/{church_id}/policies")
async def list_policies(church_id: str) -> Dict[str, Any]:
    """List policy cards for a church."""
    try:
        cards, total = card_store.list_policy_cards(church_id, limit=100)
        return {
            "church_id": church_id,
            "cards": cards,
            "total": total,
            "count": len(cards),
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


_DEFAULT_CHURCH = os.environ.get("EMBARK_DEFAULT_CHURCH", "holy_comforter")
_DEFAULT_VOTER = os.environ.get("EMBARK_DEFAULT_VOTER", "anonymous")


@action_router.post("/{policy_id}/vote")
async def vote_on_policy(
    policy_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    church_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    body = body or {}
    _ = church_id or body.get("church_id") or _DEFAULT_CHURCH  # reserved for multi-tenant
    voter_id = body.get("voter_id") or body.get("actor") or _DEFAULT_VOTER
    value = body.get("value") or body.get("vote")
    rationale = body.get("rationale")
    if not value:
        raise HTTPException(status_code=400, detail="missing 'vote' or 'value' in body")

    try:
        rec = await _vote_on_policy(policy_id, voter_id, value, rationale)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "policy_id": policy_id,
        "vote": rec,
    }
