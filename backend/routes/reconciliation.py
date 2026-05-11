"""Phase 5: Reconciliation queue endpoints.

GET /api/churches/{church_id}/reconciliations/latest
  Return the most-recent reconciliation summary (read from RECONCILIATION_CARD
  JSONL store; falls back to a minimal stub when none exist).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter(prefix="/api/churches", tags=["reconciliation-queue"])

def _jsonl_dir() -> Path:
    return Path(os.environ.get(
        "EMBARK_CARD_JSONL_DIR",
        str(Path(__file__).resolve().parents[1] / "data" / "cards"),
    ))


def _read_reconciliation_cards(church_id: str) -> list[Dict[str, Any]]:
    p = _jsonl_dir() / f"reconciliations_{church_id}.jsonl"
    if not p.exists():
        return []
    out: list[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


@router.get("/{church_id}/reconciliations/latest")
async def latest_reconciliation(church_id: str) -> Dict[str, Any]:
    records = _read_reconciliation_cards(church_id)
    if not records:
        return {
            "church_id": church_id,
            "found": False,
            "summary": {
                "run_id": None,
                "completed_at": None,
                "matched_count": 0,
                "unmatched_count": 0,
                "exception_count": 0,
            },
        }
    records.sort(key=lambda r: r.get("completed_at", r.get("created_at", "")), reverse=True)
    latest = records[0]
    return {
        "church_id": church_id,
        "found": True,
        "summary": {
            "run_id": latest.get("run_id"),
            "completed_at": latest.get("completed_at") or latest.get("created_at"),
            "matched_count": latest.get("matched_count", 0),
            "unmatched_count": latest.get("unmatched_count", 0),
            "exception_count": latest.get("exception_count", 0),
        },
        "latest": latest,
    }
