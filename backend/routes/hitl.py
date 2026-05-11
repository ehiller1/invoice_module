"""Phase 6: HITL decision endpoint.

POST /v2/hitl/{episode_id}/decision
  Accepts a signed DecisionToken, verifies it, injects the decision into the
  Episode Card, and flips the episode back to RUNNING so the Flow can resume.

GET /v2/hitl/{episode_id}
  Returns the current pending question + status (debug/UI convenience).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Path as FPath
from pydantic import BaseModel, Field

from backend.membrane.hitl import (
    DecisionToken,
    HITLGate,
    InvalidSignatureError,
    TokenExpiredError,
    UnknownKeyError,
)
from backend.membrane.hitl.token_signer import get_default_signer
from backend.skills.episode_card import FileEpisodeCardStore


router = APIRouter(prefix="/v2/hitl", tags=["hitl"])


# ---- module-scoped gate (overridable from tests via set_gate_for_tests) -----
_gate: Optional[HITLGate] = None


def get_gate() -> HITLGate:
    global _gate
    if _gate is None:
        _gate = HITLGate(store=FileEpisodeCardStore(), signer=get_default_signer())
    return _gate


def set_gate_for_tests(gate: Optional[HITLGate]) -> None:
    """Replace the module-level gate. Pass None to reset."""
    global _gate
    _gate = gate


# ----------------------------------------------------------------- schemas
class DecisionRequest(BaseModel):
    """Wraps a signed DecisionToken in the request body."""

    token: DecisionToken = Field(..., description="Signed decision token")


class DecisionResponse(BaseModel):
    episode_id: str
    status: str
    decision: str
    resumed: bool = True


# ----------------------------------------------------------------- endpoints
@router.post("/{episode_id}/decision", response_model=DecisionResponse)
async def submit_decision(
    episode_id: str = FPath(..., description="Episode card id"),
    body: DecisionRequest = Body(...),
) -> DecisionResponse:
    """Submit a signed human decision and resume the Flow."""
    token = body.token
    if token.episode_id != episode_id:
        raise HTTPException(
            status_code=400,
            detail=f"path episode_id ({episode_id}) does not match token ({token.episode_id})",
        )

    gate = get_gate()
    try:
        card = gate.resume(token)
    except UnknownKeyError as exc:
        raise HTTPException(status_code=401, detail=f"unknown signing key: {exc}") from exc
    except TokenExpiredError as exc:
        raise HTTPException(status_code=401, detail=f"token expired: {exc}") from exc
    except InvalidSignatureError as exc:
        raise HTTPException(status_code=401, detail=f"invalid signature: {exc}") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return DecisionResponse(
        episode_id=card.episode_id,
        status=card.status,
        decision=token.decision,
        resumed=True,
    )


@router.get("/{episode_id}")
async def get_pending(episode_id: str) -> Dict[str, Any]:
    """Return the current state of an episode (status + any pending question)."""
    card = get_gate().store.read(episode_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"episode {episode_id} not found")
    return {
        "episode_id": card.episode_id,
        "status": card.status,
        "pending": card.last_output.get("hitl_pending"),
        "resolution": card.last_output.get("hitl_resolution"),
    }


__all__ = ["router", "get_gate", "set_gate_for_tests"]
