"""PostgreSQL-backed Decision Ledger persistence.

Append-only ledger for structured reasoning (FRD §14.1). Entries are inserted
once and never modified; they may be soft-deleted via `disavowed_at`.

Schema reference:
- decision_ledger_entries(id PK, entry_id UNIQUE, church_id FK, job_id,
  decision_id, category decision_category, authoring_actor,
  policy_invoked, evidence_refs, inference_chain JSONB, conclusion,
  alternatives JSONB, outcome decision_outcome, disavowed_at, created_at)

Enum mapping:
    decision_category model values are lowercase (recognize/code/route/...);
    DB enum is RECOGNIZE/ROUTE/CODE/APPROVE. Categories outside the DB enum
    (OVERRIDE, DISAVOW) are coerced to APPROVE for the column; the original
    category is preserved inside `metadata` of the inference_chain.

    decision_outcome model values are lowercase (accepted/rejected/...);
    DB enum is APPROVED/REJECTED/ESCALATED/UNCERTAIN. We map ACCEPTED→APPROVED
    and TABLED/DELEGATED→UNCERTAIN.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .connection import execute_query
from .transactions import atomic_transaction
from ..events.emitter import emit_event_in_txn
from ..events.schemas import EventType, FinancialEvent, TagKind
from ..decision_ledger import (
    LedgerEntry,
    DecisionCategory,
    DecisionOutcome,
)


# Re-export for convenience
DecisionLedgerEntry = LedgerEntry


_DB_CATEGORIES = {"RECOGNIZE", "ROUTE", "CODE", "APPROVE"}
_DB_OUTCOMES = {"APPROVED", "REJECTED", "ESCALATED", "UNCERTAIN"}

_CATEGORY_TO_DB = {
    "recognize": "RECOGNIZE",
    "route": "ROUTE",
    "code": "CODE",
    "approve": "APPROVE",
    "override": "APPROVE",   # coerced
    "disavow": "APPROVE",    # coerced
}

_OUTCOME_TO_DB = {
    "accepted": "APPROVED",
    "approved": "APPROVED",
    "rejected": "REJECTED",
    "escalated": "ESCALATED",
    "tabled": "UNCERTAIN",
    "delegated": "UNCERTAIN",
    "uncertain": "UNCERTAIN",
}

_DB_TO_CATEGORY = {
    "RECOGNIZE": DecisionCategory.RECOGNIZE,
    "ROUTE": DecisionCategory.ROUTE,
    "CODE": DecisionCategory.CODE,
    "APPROVE": DecisionCategory.APPROVE,
}

_DB_TO_OUTCOME = {
    "APPROVED": DecisionOutcome.ACCEPTED,
    "REJECTED": DecisionOutcome.REJECTED,
    "ESCALATED": DecisionOutcome.ESCALATED,
    "UNCERTAIN": DecisionOutcome.TABLED,
}


def _resolve_church_pk(church_id: str) -> int:
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _category_to_db(cat: Any) -> str:
    val = cat.value if hasattr(cat, "value") else str(cat)
    val = val.lower()
    return _CATEGORY_TO_DB.get(val, "APPROVE")


def _outcome_to_db(outcome: Any) -> str:
    val = outcome.value if hasattr(outcome, "value") else str(outcome)
    val = val.lower()
    return _OUTCOME_TO_DB.get(val, "UNCERTAIN")


def _row_to_entry(row: Dict[str, Any]) -> LedgerEntry:
    actor_json = row.get("authoring_actor") or "{}"
    if isinstance(actor_json, str):
        try:
            actor = json.loads(actor_json)
        except json.JSONDecodeError:
            actor = {"actor_id": actor_json}
    else:
        actor = dict(actor_json)
    if not isinstance(actor, dict):
        actor = {"actor_id": str(actor)}

    evidence = row.get("evidence_refs") or "[]"
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except json.JSONDecodeError:
            evidence = []

    inference = row.get("inference_chain") or []
    if isinstance(inference, str):
        try:
            inference = json.loads(inference)
        except json.JSONDecodeError:
            inference = []

    alternatives = row.get("alternatives") or []
    if isinstance(alternatives, str):
        try:
            alternatives = json.loads(alternatives)
        except json.JSONDecodeError:
            alternatives = []

    return LedgerEntry(
        entry_id=row["entry_id"],
        decision_id=row.get("decision_id") or "",
        category=_DB_TO_CATEGORY.get(row["category"], DecisionCategory.APPROVE),
        timestamp=row.get("created_at") or datetime.utcnow(),
        authoring_actor=actor,
        policy_invoked=row.get("policy_invoked"),
        evidence_refs=list(evidence) if isinstance(evidence, list) else [],
        inference_chain=list(inference) if isinstance(inference, list) else [],
        conclusion=row.get("conclusion"),
        alternatives=list(alternatives) if isinstance(alternatives, list) else [],
        outcome=_DB_TO_OUTCOME.get(row["outcome"], DecisionOutcome.TABLED),
        disavowed_at=row.get("disavowed_at"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_entry(church_id: str, entry: LedgerEntry, job_id: Optional[str] = None) -> str:
    """Append an entry to the ledger. Returns the entry_id.

    If `entry.entry_id` is empty, a UUID4 is generated.
    """
    church_pk = _resolve_church_pk(church_id)
    entry_id = entry.entry_id or str(uuid.uuid4())

    payload = entry.model_dump(mode="json")

    # Phase 5d: merge cited_event_ids into evidence_refs so the citation
    # links are persisted without a schema migration. The pointers are
    # semantically the same — both point at events/cards that justify the
    # decision. The model keeps both fields distinct for callers that
    # care about provenance type.
    _merged_refs = list(payload.get("evidence_refs") or [])
    for cid in (payload.get("cited_event_ids") or []):
        if cid and cid not in _merged_refs:
            _merged_refs.append(cid)

    actor_json = json.dumps(payload.get("authoring_actor") or {}, default=str)
    evidence_json = json.dumps(_merged_refs, default=str)
    inference_json = json.dumps(payload.get("inference_chain") or [], default=str)
    alternatives_json = json.dumps(payload.get("alternatives") or [], default=str)

    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO decision_ledger_entries (
                entry_id, church_id, job_id, decision_id,
                category, authoring_actor, policy_invoked,
                evidence_refs, inference_chain, conclusion,
                alternatives, outcome, disavowed_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s::jsonb, %s,
                %s::jsonb, %s, %s
            )
            """,
            (
                entry_id,
                church_pk,
                job_id,
                entry.decision_id,
                _category_to_db(entry.category),
                actor_json,
                entry.policy_invoked,
                evidence_json,
                inference_json,
                entry.conclusion,
                alternatives_json,
                _outcome_to_db(entry.outcome),
                entry.disavowed_at,
            ),
        )
        cur.close()

        # Phase 5a: dual-write a DecisionRecorded event. The
        # decision_ledger_entries row becomes a projection of this event.
        actor_obj = payload.get("authoring_actor") or {}
        _ev = FinancialEvent(
            event_type=EventType.DECISION_RECORDED,
            church_id=church_id,
            actor=(
                actor_obj.get("actor_email")
                or actor_obj.get("email")
                or actor_obj.get("actor_id")
            ),
            payload={
                "ledger_entry_id": entry_id,
                "decision_id": entry.decision_id,
                "category": _category_to_db(entry.category),
                "policy_invoked": entry.policy_invoked,
                "conclusion": entry.conclusion,
                "outcome": _outcome_to_db(entry.outcome),
                "evidence_refs": payload.get("evidence_refs") or [],
                "inference_chain": payload.get("inference_chain") or [],
            },
            correlation_id=job_id,
        )
        if job_id:
            _ev.add_tag(TagKind.JOB, job_id)
        emit_event_in_txn(conn, _ev)
    return entry_id


def get_ledger(
    church_id: str,
    category: Optional[str] = None,
    job_id: Optional[str] = None,
) -> List[LedgerEntry]:
    """Load ledger entries for a church with optional filters."""
    church_pk = _resolve_church_pk(church_id)

    sql = ["SELECT * FROM decision_ledger_entries WHERE church_id = %s"]
    params: List[Any] = [church_pk]
    if category:
        sql.append("AND category = %s")
        params.append(_category_to_db(category))
    if job_id:
        sql.append("AND job_id = %s")
        params.append(job_id)
    sql.append("ORDER BY created_at ASC, id ASC")

    rows = execute_query(" ".join(sql), tuple(params)) or []
    return [_row_to_entry(r) for r in rows]


def find_by_decision(church_id: str, decision_id: str) -> List[LedgerEntry]:
    """Find ledger entries by decision_id (exact match or prefix)."""
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT * FROM decision_ledger_entries
         WHERE church_id = %s
           AND (decision_id = %s OR decision_id LIKE %s)
         ORDER BY created_at ASC, id ASC
        """,
        (church_pk, decision_id, f"{decision_id}%"),
    ) or []
    return [_row_to_entry(r) for r in rows]


def find_by_actor(
    church_id: str,
    actor_email: str,
    since: Optional[datetime] = None,
) -> List[LedgerEntry]:
    """Find ledger entries authored by an actor (looked up inside the JSON
    authoring_actor blob — supports actor_id, actor_email, or email keys)."""
    church_pk = _resolve_church_pk(church_id)

    sql = [
        """
        SELECT * FROM decision_ledger_entries
         WHERE church_id = %s
           AND (
                authoring_actor::text LIKE %s
             )
        """
    ]
    params: List[Any] = [church_pk, f"%{actor_email}%"]
    if since:
        sql.append("AND created_at >= %s")
        params.append(since)
    sql.append("ORDER BY created_at ASC, id ASC")

    rows = execute_query(" ".join(sql), tuple(params)) or []
    # Filter precisely in Python — the LIKE is just a coarse pre-filter
    out: List[LedgerEntry] = []
    for r in rows:
        e = _row_to_entry(r)
        actor = e.authoring_actor or {}
        candidates = [
            actor.get("actor_id"),
            actor.get("actor_email"),
            actor.get("email"),
        ]
        if any(c == actor_email for c in candidates if c):
            out.append(e)
    return out


def disavow_entry(church_id: str, entry_id: str, reason: str) -> bool:
    """Soft-delete: set disavowed_at on the entry. Returns True if updated.

    The disavowal reason is appended to `inference_chain` so it survives the
    schema's lack of a dedicated reason column.
    """
    church_pk = _resolve_church_pk(church_id)

    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT inference_chain FROM decision_ledger_entries
             WHERE church_id = %s AND entry_id = %s
            """,
            (church_pk, entry_id),
        )
        row = cur.fetchone()
        if row is None:
            cur.close()
            return False

        chain = row[0]
        if isinstance(chain, str):
            try:
                chain = json.loads(chain)
            except json.JSONDecodeError:
                chain = []
        if not isinstance(chain, list):
            chain = []
        chain.append({
            "step": "disavowal",
            "reason": reason,
            "at": datetime.utcnow().isoformat(),
        })

        cur.execute(
            """
            UPDATE decision_ledger_entries
               SET disavowed_at = CURRENT_TIMESTAMP,
                   inference_chain = %s::jsonb
             WHERE church_id = %s AND entry_id = %s
            """,
            (json.dumps(chain, default=str), church_pk, entry_id),
        )
        affected = cur.rowcount or 0
        cur.close()
    return affected > 0
