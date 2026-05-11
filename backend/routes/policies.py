"""Phase 5: Policies Queue action endpoints.

POST /api/policies/{id}/vote
  Body: {voter_id, value: "YES"|"NO"|"ABSTAIN", church_id?}
  Returns the updated tally and quorum status.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from ..tools import policy_store

router = APIRouter(prefix="/api/policies", tags=["policies-queue"])

_DEFAULT_CHURCH = os.environ.get("EMBARK_DEFAULT_CHURCH", "holy_comforter")


@router.post("/{policy_id}/vote")
async def vote_on_policy(
    policy_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    church_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    body = body or {}
    ch = church_id or body.get("church_id") or _DEFAULT_CHURCH
    voter_id = body.get("voter_id") or body.get("actor")
    value = body.get("value") or body.get("vote")
    if not voter_id or not value:
        raise HTTPException(status_code=400, detail="missing 'voter_id' or 'value' in body")

    try:
        rec = policy_store.record_vote(ch, policy_id, voter_id=voter_id, value=value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    quorum = policy_store.check_quorum(ch, policy_id)
    return {
        "ok": True,
        "policy_id": policy_id,
        "tally": (rec or {}).get("tally"),
        "status": (rec or {}).get("status"),
        "quorum": quorum,
    }
