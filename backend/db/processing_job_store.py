"""PostgreSQL-backed ProcessingJob persistence.

Replaces the in-memory job dict in `main.py`. The full ProcessingJob model is
serialised as JSONB in the `payload` column for flexibility; the top-level
status column allows efficient filtering.

Schema reference:
- processing_jobs(id PK, job_id UNIQUE, church_id FK, status processing_status,
  created_at, updated_at, payload JSONB)

Status mapping: the model's ProcessingStatus enum has more values than the DB
enum. We map model statuses onto the DB-supported set for the column; the
authoritative status is always the one inside `payload.status`.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2.extras

from .connection import execute_query
from .transactions import atomic_transaction
from ..models.schemas import ProcessingJob, ProcessingStatus


# DB enum values: 'RECEIVED','EXTRACTING','CLASSIFYING','MAPPING','REVIEW','COMPLETING','FAILED'
_MODEL_TO_DB_STATUS = {
    ProcessingStatus.UPLOADED.value: "RECEIVED",
    ProcessingStatus.EXTRACTING.value: "EXTRACTING",
    ProcessingStatus.CLASSIFYING.value: "CLASSIFYING",
    ProcessingStatus.MAPPING.value: "MAPPING",
    ProcessingStatus.REVIEWING.value: "REVIEW",
    ProcessingStatus.PENDING_HITL.value: "REVIEW",
    ProcessingStatus.PENDING_BUDGET_OWNER.value: "REVIEW",
    ProcessingStatus.PENDING_TREASURER.value: "REVIEW",
    ProcessingStatus.BUDGET_OWNER_APPROVED.value: "REVIEW",
    ProcessingStatus.TREASURER_APPROVED.value: "REVIEW",
    ProcessingStatus.BUILDING_ENTRY.value: "COMPLETING",
    ProcessingStatus.EMITTED.value: "COMPLETING",
    ProcessingStatus.REJECTED.value: "FAILED",
    ProcessingStatus.ERROR.value: "FAILED",
    ProcessingStatus.BLOCKED_FUND_RESTRICTION.value: "FAILED",
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


def _model_status_to_db(status: Any) -> str:
    val = status.value if hasattr(status, "value") else str(status)
    return _MODEL_TO_DB_STATUS.get(val, "RECEIVED")


def _payload_dict(job: ProcessingJob) -> Dict[str, Any]:
    """Serialise the job to a JSON-safe dict (Decimal→str, datetime→ISO)."""
    return job.model_dump(mode="json")


def _row_to_job(row: Dict[str, Any]) -> ProcessingJob:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return ProcessingJob.model_validate(payload)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_job(church_id: str, job: ProcessingJob) -> str:
    """Insert a processing job, returning its job_id."""
    church_pk = _resolve_church_pk(church_id)
    payload = _payload_dict(job)

    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO processing_jobs (job_id, church_id, status, payload)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (job_id) DO UPDATE SET
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = CURRENT_TIMESTAMP
            RETURNING job_id
            """,
            (
                job.job_id,
                church_pk,
                _model_status_to_db(job.status),
                json.dumps(payload, default=str),
            ),
        )
        row = cur.fetchone()
        cur.close()
    return str(row[0])


def get_job(job_id: str) -> Optional[ProcessingJob]:
    """Load a job by job_id and reconstruct the ProcessingJob model."""
    row = execute_query(
        "SELECT payload FROM processing_jobs WHERE job_id = %s",
        (job_id,),
        fetch_one=True,
    )
    if row is None:
        return None
    return _row_to_job(row)


def update_job(job_id: str, updates: Dict[str, Any]) -> bool:
    """Update specific fields on a job by patching its payload.

    `updates` is a dict of model field names → new values. The full model is
    re-validated after the patch so type errors surface immediately. The
    top-level `status` column is also updated when present.
    """
    if not updates:
        return False

    job = get_job(job_id)
    if job is None:
        return False

    patched = job.model_dump(mode="json")
    for k, v in updates.items():
        # Convert datetime/Decimal/Enum to JSON-safe form to keep payload roundtrippable
        if hasattr(v, "value"):
            patched[k] = v.value
        elif isinstance(v, datetime):
            patched[k] = v.isoformat()
        else:
            patched[k] = v
    patched["updated_at"] = datetime.utcnow().isoformat()

    new_job = ProcessingJob.model_validate(patched)

    count = execute_query(
        """
        UPDATE processing_jobs
           SET status = %s,
               payload = %s::jsonb,
               updated_at = CURRENT_TIMESTAMP
         WHERE job_id = %s
        """,
        (
            _model_status_to_db(new_job.status),
            json.dumps(new_job.model_dump(mode="json"), default=str),
            job_id,
        ),
    )
    return bool(count and count > 0)


def list_jobs(
    church_id: str,
    since: Optional[datetime] = None,
    status: Optional[str] = None,
) -> List[ProcessingJob]:
    """List jobs for a church with optional filters.

    `status` accepts either a model status (e.g. 'PENDING_HITL') or a DB enum
    value (e.g. 'REVIEW'); both are mapped before filtering.
    """
    church_pk = _resolve_church_pk(church_id)

    sql = ["SELECT payload FROM processing_jobs WHERE church_id = %s"]
    params: List[Any] = [church_pk]
    if since:
        sql.append("AND created_at >= %s")
        params.append(since)
    if status:
        db_status = _MODEL_TO_DB_STATUS.get(status, status)
        sql.append("AND status = %s")
        params.append(db_status)
    sql.append("ORDER BY created_at DESC")

    rows = execute_query(" ".join(sql), tuple(params)) or []
    return [_row_to_job(r) for r in rows]


def delete_job(job_id: str) -> bool:
    """Delete a job. Cascade behaviour follows FKs in the schema."""
    count = execute_query(
        "DELETE FROM processing_jobs WHERE job_id = %s",
        (job_id,),
    )
    return bool(count and count > 0)
