"""POLICY_CARD store with vote tracking (Phase 5).

Voting is tallied against a configurable quorum. JSONL-backed during the
Phase 5-10 dual-write transition.
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

DEFAULT_QUORUM = int(os.environ.get("EMBARK_POLICY_QUORUM", "3"))


def _path(church_id: str) -> Path:
    _JSONL_DIR.mkdir(parents=True, exist_ok=True)
    return _JSONL_DIR / f"policies_{church_id}.jsonl"


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
    by_id: Dict[str, Dict[str, Any]] = {}
    for rec in out:
        by_id[rec.get("policy_id", str(uuid.uuid4()))] = rec
    return list(by_id.values())


def _append(church_id: str, rec: Dict[str, Any]) -> None:
    with _LOCK:
        with _path(church_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def create_policy(
    church_id: str,
    *,
    title: str,
    description: str,
    quorum: int = DEFAULT_QUORUM,
    policy_id: Optional[str] = None,
) -> Dict[str, Any]:
    pid = policy_id or f"pol-{uuid.uuid4().hex[:16]}"
    rec = {
        "policy_id": pid,
        "church_id": church_id,
        "title": title,
        "description": description,
        "quorum": int(quorum),
        "votes": {},  # voter_id -> {"value": "YES"|"NO"|"ABSTAIN", "at": ts}
        "tally": {"yes": 0, "no": 0, "abstain": 0},
        "status": "OPEN",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _append(church_id, rec)
    return rec


def get_policy(church_id: str, policy_id: str) -> Optional[Dict[str, Any]]:
    for rec in _read_all(church_id):
        if rec.get("policy_id") == policy_id:
            return rec
    return None


def list_policies(
    church_id: str, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    recs = _read_all(church_id)
    if status:
        recs = [r for r in recs if r.get("status") == status]
    recs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return recs


def record_vote(
    church_id: str,
    policy_id: str,
    *,
    voter_id: str,
    value: str,
) -> Optional[Dict[str, Any]]:
    value_norm = value.upper().strip()
    if value_norm not in ("YES", "NO", "ABSTAIN"):
        raise ValueError(f"invalid vote value: {value!r}")
    rec = get_policy(church_id, policy_id)
    if rec is None:
        # Auto-create a placeholder so vote isn't lost.
        rec = create_policy(
            church_id, title=f"(auto) {policy_id}", description="",
            policy_id=policy_id,
        )
    rec.setdefault("votes", {})[voter_id] = {
        "value": value_norm,
        "at": datetime.utcnow().isoformat(),
    }
    # Recompute tally from votes (last-write-wins per voter).
    tally = {"yes": 0, "no": 0, "abstain": 0}
    for v in rec["votes"].values():
        if v["value"] == "YES":
            tally["yes"] += 1
        elif v["value"] == "NO":
            tally["no"] += 1
        else:
            tally["abstain"] += 1
    rec["tally"] = tally
    quorum = int(rec.get("quorum", DEFAULT_QUORUM))
    decisive = max(tally["yes"], tally["no"])
    if decisive >= quorum:
        rec["status"] = "PASSED" if tally["yes"] >= tally["no"] else "REJECTED"
        rec["closed_at"] = datetime.utcnow().isoformat()
    rec["updated_at"] = datetime.utcnow().isoformat()
    _append(church_id, rec)
    return rec


def check_quorum(church_id: str, policy_id: str) -> Dict[str, Any]:
    rec = get_policy(church_id, policy_id)
    if rec is None:
        return {"reached": False, "tally": {}, "quorum": DEFAULT_QUORUM}
    tally = rec.get("tally", {"yes": 0, "no": 0, "abstain": 0})
    quorum = int(rec.get("quorum", DEFAULT_QUORUM))
    reached = max(tally.get("yes", 0), tally.get("no", 0)) >= quorum
    return {"reached": reached, "tally": tally, "quorum": quorum, "status": rec.get("status")}


__all__ = [
    "create_policy",
    "get_policy",
    "list_policies",
    "record_vote",
    "check_quorum",
    "DEFAULT_QUORUM",
]
