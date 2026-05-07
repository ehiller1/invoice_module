"""FR-05.4: append-only hash-chained approval audit log.

Each event is a JSON line in `backend/data/approvals_{church_id}.jsonl`. The
chain is enforced by storing a SHA-256 hash of the prior row's serialized
content (excluding its own `prev_hash` and `hash` fields) in every row's
`prev_hash` field. The first row stores the literal string "GENESIS".

The hash also includes the row's own canonical content, stored in `hash`,
allowing chain verification to walk the file in O(n).
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
_LOCK = threading.Lock()

GENESIS_HASH = "GENESIS"


def _store_path(church_id: str) -> Path:
    return DATA_DIR / f"approvals_{church_id}.jsonl"


def _canonical_payload(event: Dict[str, Any]) -> str:
    """Stable JSON for hashing — exclude `hash` field, include `prev_hash`."""
    payload = {k: v for k, v in event.items() if k != "hash"}
    return json.dumps(payload, sort_keys=True, default=str)


def _last_hash(p: Path) -> str:
    """Read the file (if any) and return the last row's `hash` field."""
    if not p.exists():
        return GENESIS_HASH
    last: Optional[Dict[str, Any]] = None
    with p.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                last = json.loads(ln)
            except json.JSONDecodeError:
                continue
    if not last:
        return GENESIS_HASH
    return str(last.get("hash") or GENESIS_HASH)


def append_event(church_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Append `event` to the church's approval audit chain.

    Mutates a copy of `event` to add: `event_id`, `timestamp`, `prev_hash`,
    `hash`. Returns the stored row.
    """
    p = _store_path(church_id)
    with _LOCK:
        prev = _last_hash(p)
        row = dict(event)
        row.setdefault("event_id", str(uuid.uuid4()))
        row.setdefault("timestamp", datetime.utcnow().isoformat())
        row["prev_hash"] = prev
        # Hash is over the row content INCLUDING prev_hash but EXCLUDING hash.
        digest = hashlib.sha256(_canonical_payload(row).encode("utf-8")).hexdigest()
        row["hash"] = digest
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    return row


def list_events(church_id: str, since: Optional[str] = None,
                until: Optional[str] = None,
                job_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read all rows. Optional filters: ISO date range and job_id."""
    p = _store_path(church_id)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                continue
            ts = str(row.get("timestamp") or "")
            if since and ts and ts < since:
                continue
            if until and ts and ts > until:
                continue
            if job_id and str(row.get("job_id") or "") != str(job_id):
                continue
            out.append(row)
    return out


def verify_chain(church_id: str) -> bool:
    """Walk the file and verify every `prev_hash` matches the prior `hash`,
    and every `hash` matches a fresh recomputation of the row content.
    """
    p = _store_path(church_id)
    if not p.exists():
        return True

    expected_prev = GENESIS_HASH
    with p.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                return False
            if str(row.get("prev_hash")) != expected_prev:
                return False
            recomputed = hashlib.sha256(_canonical_payload(row).encode("utf-8")).hexdigest()
            if str(row.get("hash")) != recomputed:
                return False
            expected_prev = str(row["hash"])
    return True
