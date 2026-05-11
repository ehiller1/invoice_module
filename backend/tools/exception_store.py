"""EXCEPTION_CARD store (Phase 5).

Reads/writes from the Card Store (Phase 10 DB) with JSONL append fallback
during the Phase 5-10 dual-write transition. JSONL is the local
source-of-truth until card_store.py is fully wired into postgres.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional


_JSONL_DIR = Path(os.environ.get(
    "EMBARK_CARD_JSONL_DIR",
    str(Path(__file__).resolve().parents[1] / "data" / "cards"),
))
_LOCK = Lock()


def _path(church_id: str) -> Path:
    _JSONL_DIR.mkdir(parents=True, exist_ok=True)
    return _JSONL_DIR / f"exceptions_{church_id}.jsonl"


def _read_all(church_id: str) -> List[Dict[str, Any]]:
    p = _path(church_id)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    # Dedup by card_id, keeping last write.
    by_id: Dict[str, Dict[str, Any]] = {}
    for rec in out:
        by_id[rec.get("card_id", str(uuid.uuid4()))] = rec
    return list(by_id.values())


def _append(church_id: str, rec: Dict[str, Any]) -> None:
    p = _path(church_id)
    with _LOCK:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def create_exception(
    church_id: str,
    *,
    title: str,
    description: str,
    exception_type: str = "general",
    principal: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    card_id = f"exc-{uuid.uuid4().hex[:16]}"
    rec = {
        "card_id": card_id,
        "church_id": church_id,
        "exception_type": exception_type,
        "title": title,
        "description": description,
        "principal": principal,
        "evidence": evidence or {},
        "job_id": job_id,
        "status": "OPEN",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    # Dual-write attempt — DB then JSONL fallback (always JSONL).
    try:
        from ..db import card_store as _cs
        _cs.create_exception_card(
            church_id=church_id,
            exception_type=exception_type,
            title=title,
            description=description,
            evidence=evidence,
            job_id=job_id,
        )
    except Exception:
        pass
    _append(church_id, rec)
    return rec


def get_exception(church_id: str, card_id: str) -> Optional[Dict[str, Any]]:
    for rec in _read_all(church_id):
        if rec.get("card_id") == card_id:
            return rec
    return None


def list_exceptions(
    church_id: str, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    recs = _read_all(church_id)
    if status:
        recs = [r for r in recs if r.get("status") == status]
    recs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return recs


def update_exception(
    church_id: str, card_id: str, **fields: Any
) -> Optional[Dict[str, Any]]:
    rec = get_exception(church_id, card_id)
    if rec is None:
        return None
    rec.update(fields)
    rec["updated_at"] = datetime.utcnow().isoformat()
    _append(church_id, rec)
    return rec


def write_decision(
    church_id: str,
    card_id: str,
    *,
    verdict: str,
    actor: str,
    reasoning: Optional[str] = None,
) -> Dict[str, Any]:
    """Write a DECISION_PACKET row alongside the card update."""
    packet = {
        "packet_id": f"dec-{uuid.uuid4().hex[:16]}",
        "card_id": card_id,
        "church_id": church_id,
        "verdict": verdict,
        "actor": actor,
        "reasoning": reasoning,
        "decided_at": datetime.utcnow().isoformat(),
    }
    # Append to a decisions log.
    dpath = _JSONL_DIR / f"decisions_{church_id}.jsonl"
    with _LOCK:
        _JSONL_DIR.mkdir(parents=True, exist_ok=True)
        with dpath.open("a", encoding="utf-8") as f:
            f.write(json.dumps(packet, default=str) + "\n")
    update_exception(
        church_id, card_id,
        status="RESOLVED" if verdict in ("APPROVED", "REJECTED", "RESOLVED") else "IN_REVIEW",
        last_decision=packet,
    )
    return packet


__all__ = [
    "create_exception",
    "get_exception",
    "list_exceptions",
    "update_exception",
    "write_decision",
]
