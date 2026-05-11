"""Phase 5: Recommendations Queue (NBA - Next Best Action) endpoints.

Endpoints:
  GET /api/churches/{church_id}/recommendations   — list recommendation cards for a church
  POST /api/recommendations/{id}/accept           — accept a recommendation
  POST /api/recommendations/{id}/decline          — decline a recommendation
  POST /api/recommendations/{id}/defer            — defer a recommendation
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from ..db import card_store

router = APIRouter(prefix="/api/churches", tags=["recommendations-queue"])


@router.get("/{church_id}/recommendations")
async def list_recommendations(church_id: str) -> Dict[str, Any]:
    """List recommendation cards for a church."""
    try:
        cards, total = card_store.list_recommendation_cards(church_id, limit=100)
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
