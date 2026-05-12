"""Phase 5: Policies Queue action endpoints.

POST /api/policies/{id}/vote
  Body: {voter_id?, value|vote: "approve"|"reject"|"abstain", rationale?, church_id?}
  Routes through the membrane policy_management module (canonical store).
  Identity may also be supplied via X-Voter-Id, X-User-Role, X-Church-Id headers.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from ..db import card_store
from ..db import policy_votes_store
from ..membrane.pledge.policy_management import vote_on_policy as _vote_on_policy

logger = logging.getLogger(__name__)

church_router = APIRouter(prefix="/api/churches", tags=["policies-queue"])
action_router = APIRouter(prefix="/api/policies", tags=["policies-queue"])

_DEFAULT_CHURCH = os.environ.get("EMBARK_DEFAULT_CHURCH", "holy_comforter")
_DEFAULT_VOTER = os.environ.get("EMBARK_DEFAULT_VOTER", "anonymous")
_DEFAULT_QUORUM = int(os.environ.get("EMBARK_DEFAULT_QUORUM", "3"))


def _normalize_vote(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = v.strip().lower()
    if v in ("approve", "approved", "yes"):
        return "yes"
    if v in ("reject", "rejected", "no"):
        return "no"
    if v in ("abstain",):
        return "abstain"
    return v  # let backend decide


@church_router.get("/{church_id}/policies")
async def list_policies(church_id: str) -> Dict[str, Any]:
    """List policy cards for a church, with vote tallies from the indexed table."""
    try:
        cards, total = card_store.list_policy_cards(church_id, limit=100)

        # One indexed query → all votes for these policies.
        try:
            ids = [
                (c.get("policy_id") or c.get("card_id"))
                for c in cards
                if (c.get("policy_id") or c.get("card_id"))
            ]
            votes_by_pid = policy_votes_store.votes_for_policies(ids)
        except Exception as e:  # pragma: no cover
            logger.warning("policy_votes lookup failed: %s", e)
            votes_by_pid = {}

        for c in cards:
            ev = c.get("evidence") or {}
            pid = c.get("policy_id") or c.get("card_id")
            rows = votes_by_pid.get(pid, [])
            ev["voted_by"] = [
                {
                    "voter_id":   r.get("voter_id"),
                    "voter_role": r.get("voter_role"),
                    "vote":       r.get("vote"),
                    "rationale":  r.get("rationale"),
                    "timestamp":  (r.get("cast_at").isoformat() if r.get("cast_at") else None),
                }
                for r in rows
            ]
            ev.setdefault("votes_required", _DEFAULT_QUORUM)
            c["evidence"] = ev

        return {
            "church_id": church_id,
            "cards": cards,
            "total": total,
            "count": len(cards),
            "ok": True,
        }
    except Exception as e:
        logger.exception("list_policies failed")
        return {
            "church_id": church_id,
            "cards": [],
            "total": 0,
            "count": 0,
            "ok": False,
            "error": str(e),
        }


@action_router.post("/{policy_id}/vote")
async def vote_on_policy(
    policy_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    church_id: Optional[str] = Query(default=None),
    x_voter_id: Optional[str] = Header(default=None, alias="X-Voter-Id"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
    x_church_id: Optional[str] = Header(default=None, alias="X-Church-Id"),
) -> Dict[str, Any]:
    body = body or {}
    eff_church = church_id or x_church_id or body.get("church_id") or _DEFAULT_CHURCH
    voter_id = x_voter_id or body.get("voter_id") or body.get("actor") or _DEFAULT_VOTER
    voter_role = x_user_role or body.get("voter_role")
    if voter_id == "guest" or voter_id == _DEFAULT_VOTER:
        # Don't accept anonymous votes — Flow 8 needs identity.
        raise HTTPException(
            status_code=401,
            detail="A real signed-in user is required to vote. Switch user from the sidebar chip.",
        )

    value = _normalize_vote(body.get("value") or body.get("vote"))
    rationale = body.get("rationale")
    if not value:
        raise HTTPException(status_code=400, detail="missing 'vote' or 'value' in body")

    # Write to the indexed policy_votes table.
    try:
        rec = policy_votes_store.record_vote(
            policy_id,
            voter_id,
            value,
            church_id=eff_church,
            voter_role=voter_role,
            rationale=rationale,
        )
    except Exception as e:
        logger.exception("policy_votes write failed")
        raise HTTPException(status_code=500, detail=f"vote storage failed: {e}")

    # Mirror into the legacy CardStore for downstream listeners.
    try:
        await _vote_on_policy(policy_id, voter_id, value, rationale)
    except Exception as e:  # pragma: no cover — best effort mirror
        logger.warning("legacy vote mirror failed: %s", e)

    # Promote to ACTIVE if quorum reached. We use the per-policy votes_required
    # from evidence when present, otherwise the env default.
    activated = False
    try:
        cards, _ = card_store.list_policy_cards(eff_church, limit=200)
        card = next(
            (c for c in cards if (c.get("policy_id") == policy_id or c.get("card_id") == policy_id)),
            None,
        )
        if card and (card.get("status") or "").upper() == "OPEN":
            tally = policy_votes_store.tally(policy_id)
            ev = card.get("evidence") or {}
            quorum = int(ev.get("votes_required") or _DEFAULT_QUORUM)
            if tally["yes"] >= quorum:
                _activate_policy_card(card.get("card_id"))
                activated = True
                logger.info("Policy %s activated after reaching quorum %s", policy_id, quorum)
    except Exception as e:  # pragma: no cover
        logger.warning("quorum check failed for %s: %s", policy_id, e)

    return {
        "ok": True,
        "policy_id": policy_id,
        "vote": rec,
        "activated": activated,
    }


def _activate_policy_card(card_id: Optional[str]) -> None:
    """Promote a policy card past OPEN once quorum is reached.

    The card_status enum allows OPEN/IN_REVIEW/RESOLVED/CANCELLED — we use
    RESOLVED with resolution_data.decision='approved' to denote 'policy active'.
    """
    if not card_id:
        return
    import json
    from ..db.connection import execute_query
    payload = json.dumps({"decision": "approved", "promoted_by": "quorum"})
    execute_query(
        "UPDATE policy_cards SET status='RESOLVED', resolved_at=NOW(), "
        "resolution_data = COALESCE(resolution_data, '{}'::jsonb) || %s::jsonb "
        "WHERE card_id=%s",
        (payload, card_id),
    )
