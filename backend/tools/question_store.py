"""QUESTION_CARD store (Phase 5).

Persists user questions and human/analytical answers. Uses JSONL append-only
storage during the Phase 5-10 dual-write window.
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
    return _JSONL_DIR / f"questions_{church_id}.jsonl"


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
        by_id[rec.get("question_id", str(uuid.uuid4()))] = rec
    return list(by_id.values())


def _append(church_id: str, rec: Dict[str, Any]) -> None:
    with _LOCK:
        with _path(church_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def create_question(
    church_id: str,
    *,
    query: str,
    intent: Optional[str] = None,
    asker: Optional[str] = None,
) -> Dict[str, Any]:
    qid = f"q-{uuid.uuid4().hex[:16]}"
    rec = {
        "question_id": qid,
        "church_id": church_id,
        "query": query,
        "intent": intent,
        "asker": asker,
        "answers": [],
        "status": "OPEN",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _append(church_id, rec)
    return rec


def get_question(church_id: str, question_id: str) -> Optional[Dict[str, Any]]:
    for rec in _read_all(church_id):
        if rec.get("question_id") == question_id:
            return rec
    return None


def list_questions(
    church_id: str, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    recs = _read_all(church_id)
    if status:
        recs = [r for r in recs if r.get("status") == status]
    recs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return recs


def record_answer(
    church_id: str,
    question_id: str,
    *,
    answer: str,
    answerer: str,
    confidence: Optional[float] = None,
    reasoning: Optional[str] = None,
    source: str = "human",
) -> Optional[Dict[str, Any]]:
    rec = get_question(church_id, question_id)
    if rec is None:
        # Materialize a record if not found (so /answer can record against unknown id).
        rec = {
            "question_id": question_id,
            "church_id": church_id,
            "query": "",
            "intent": None,
            "answers": [],
            "status": "OPEN",
            "created_at": datetime.utcnow().isoformat(),
        }
    rec.setdefault("answers", []).append({
        "answer": answer,
        "answerer": answerer,
        "confidence": confidence,
        "reasoning": reasoning,
        "source": source,
        "recorded_at": datetime.utcnow().isoformat(),
    })
    rec["status"] = "ANSWERED"
    rec["updated_at"] = datetime.utcnow().isoformat()
    _append(church_id, rec)
    return rec


__all__ = [
    "create_question",
    "get_question",
    "list_questions",
    "record_answer",
]
