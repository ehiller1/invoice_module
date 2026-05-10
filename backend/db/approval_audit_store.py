"""Database-backed approval audit trail with SHA-256 hash chaining for tamper detection."""
from datetime import datetime
from typing import List, Optional, Dict, Any
from decimal import Decimal
import hashlib
import json
from .connection import execute_query, get_connection
from .transactions import atomic_transaction
from ..events.emitter import emit_event_in_txn
from ..events.schemas import EventType, FinancialEvent, TagKind


def _resolve_church_pk(church_id: str) -> int:
    """Resolve string church_id to integer PK."""
    result = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    )
    if not result:
        raise ValueError(f"Unknown church_id: {church_id}")
    return result["id"]


def _compute_hash(event_dict: dict, prev_hash: str = "0" * 64) -> str:
    """Compute SHA-256 hash for an event (includes previous hash for chaining)."""
    # Serialize event in sorted order for deterministic hashing
    event_str = json.dumps(event_dict, sort_keys=True, default=str)
    combined = prev_hash + event_str
    return hashlib.sha256(combined.encode()).hexdigest()


def append_event(
    church_id: str,
    event_id: str,
    job_id: Optional[str] = None,
    line_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    actor_role: Optional[str] = None,
    action: Optional[str] = None,
    gl_at_action: Optional[str] = None,
    original_gl: Optional[str] = None,
    rationale: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Append a new approval audit event with hash chaining.

    Args:
        church_id: Church identifier
        event_id: Unique event identifier (UUID)
        job_id: Processing job ID (optional)
        line_id: JE line ID (optional)
        actor_email: Email of approver/actor
        actor_role: Role of actor (TREASURER, ACCOUNTANT, ADMIN)
        action: Action taken (APPROVE, REJECT, ESCALATE, OVERRIDE)
        gl_at_action: GL account at time of action
        original_gl: Original GL account (if changed)
        rationale: Why the action was taken
        notes: Additional notes

    Returns:
        event_id (same as input, for confirmation)

    Raises:
        ValueError: If church_id doesn't exist or hash chain is broken
    """
    church_pk = _resolve_church_pk(church_id)

    # Get previous event hash (for chaining)
    prev_result = execute_query(
        "SELECT hash FROM approval_audit_events WHERE church_id = %s ORDER BY timestamp DESC LIMIT 1",
        (church_pk,),
        fetch_one=True
    )
    prev_hash = prev_result["hash"] if prev_result else "0" * 64

    # Build event dict and compute hash
    event_dict = {
        "event_id": event_id,
        "job_id": job_id,
        "line_id": line_id,
        "actor_email": actor_email,
        "actor_role": actor_role,
        "action": action,
        "gl_at_action": gl_at_action,
        "original_gl": original_gl,
        "rationale": rationale,
        "notes": notes,
        "timestamp": datetime.utcnow().isoformat(),
    }

    hash_val = _compute_hash(event_dict, prev_hash)

    # Insert event
    with atomic_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO approval_audit_events (
                event_id, church_id, job_id, line_id, actor_email, actor_role,
                action, gl_at_action, original_gl, rationale, notes,
                prev_hash, hash, timestamp
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            event_id, church_pk, job_id, line_id, actor_email, actor_role,
            action, gl_at_action, original_gl, rationale, notes,
            prev_hash, hash_val, event_dict["timestamp"]
        ))
        cursor.close()

        # Phase 5a: dual-write to event log. The approval_audit_events row
        # becomes a projection of these DecisionRecorded / Approval* events.
        _et = EventType.APPROVAL_GRANTED
        if action == "REJECT" or action == "DENY":
            _et = EventType.APPROVAL_DENIED
        elif action in ("ESCALATE", "OVERRIDE"):
            _et = EventType.DECISION_RECORDED
        _ev = FinancialEvent(
            event_type=_et,
            church_id=church_id,
            actor=actor_email,
            payload={
                "audit_event_id": event_id,
                "action": action,
                "actor_role": actor_role,
                "gl_at_action": gl_at_action,
                "original_gl": original_gl,
                "rationale": rationale,
                "notes": notes,
                "prev_hash": prev_hash,
                "hash": hash_val,
            },
            correlation_id=job_id,
        )
        if job_id:
            _ev.add_tag(TagKind.JOB, job_id)
        if gl_at_action:
            _ev.add_tag(TagKind.ACCOUNT, gl_at_action)
        emit_event_in_txn(conn, _ev)

    return event_id


def list_events(
    church_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    job_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """List approval audit events with optional filtering.

    Args:
        church_id: Church identifier
        since: Start of date range (inclusive)
        until: End of date range (inclusive)
        job_id: Filter by job ID
        actor_email: Filter by actor email
        limit: Max results to return

    Returns:
        List of audit event dicts in reverse chronological order
    """
    church_pk = _resolve_church_pk(church_id)

    query = "SELECT * FROM approval_audit_events WHERE church_id = %s"
    params = [church_pk]

    if since:
        query += " AND timestamp >= %s"
        params.append(since.isoformat() if isinstance(since, datetime) else since)

    if until:
        query += " AND timestamp <= %s"
        params.append(until.isoformat() if isinstance(until, datetime) else until)

    if job_id:
        query += " AND job_id = %s"
        params.append(job_id)

    if actor_email:
        query += " AND actor_email = %s"
        params.append(actor_email)

    query += " ORDER BY timestamp DESC LIMIT %s"
    params.append(limit)

    return execute_query(query, tuple(params), fetch_one=False)


def verify_chain(church_id: str) -> bool:
    """Verify the hash chain integrity for all events.

    Walks through all events in chronological order, recomputing hashes
    to ensure no tampering has occurred.

    Args:
        church_id: Church identifier

    Returns:
        True if all hashes are valid, False if any mismatch found

    Raises:
        ValueError: If church_id doesn't exist
    """
    church_pk = _resolve_church_pk(church_id)

    events = execute_query(
        """SELECT event_id, job_id, line_id, actor_email, actor_role, action,
                 gl_at_action, original_gl, rationale, notes, hash, prev_hash, timestamp
           FROM approval_audit_events WHERE church_id = %s ORDER BY timestamp ASC""",
        (church_pk,),
        fetch_one=False
    )

    if not events:
        return True  # Empty chain is valid

    prev_hash = "0" * 64
    for event in events:
        # Reconstruct event dict (excluding hash fields)
        event_dict = {
            "event_id": event["event_id"],
            "job_id": event["job_id"],
            "line_id": event["line_id"],
            "actor_email": event["actor_email"],
            "actor_role": event["actor_role"],
            "action": event["action"],
            "gl_at_action": event["gl_at_action"],
            "original_gl": event["original_gl"],
            "rationale": event["rationale"],
            "notes": event["notes"],
            "timestamp": event["timestamp"],
        }

        # Verify prev_hash matches
        if event["prev_hash"] != prev_hash:
            print(f"[AUDIT] Hash chain broken at event {event['event_id']}: expected prev_hash={prev_hash}, got {event['prev_hash']}")
            return False

        # Recompute hash
        computed_hash = _compute_hash(event_dict, prev_hash)
        if computed_hash != event["hash"]:
            print(f"[AUDIT] Hash mismatch at event {event['event_id']}: expected {computed_hash}, got {event['hash']}")
            return False

        prev_hash = event["hash"]

    print(f"[AUDIT] Chain verification passed for church {church_id} ({len(events)} events)")
    return True


def get_event(church_id: str, event_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a specific audit event by ID.

    Args:
        church_id: Church identifier
        event_id: Event ID

    Returns:
        Event dict or None if not found
    """
    church_pk = _resolve_church_pk(church_id)

    return execute_query(
        "SELECT * FROM approval_audit_events WHERE church_id = %s AND event_id = %s",
        (church_pk, event_id),
        fetch_one=True
    )


def count_events(
    church_id: str,
    since: Optional[datetime] = None,
    job_id: Optional[str] = None,
) -> int:
    """Count approval audit events (for pagination, statistics).

    Args:
        church_id: Church identifier
        since: Count events after this timestamp (optional)
        job_id: Count events for specific job (optional)

    Returns:
        Count of matching events
    """
    church_pk = _resolve_church_pk(church_id)

    query = "SELECT COUNT(*) as cnt FROM approval_audit_events WHERE church_id = %s"
    params = [church_pk]

    if since:
        query += " AND timestamp >= %s"
        params.append(since.isoformat() if isinstance(since, datetime) else since)

    if job_id:
        query += " AND job_id = %s"
        params.append(job_id)

    result = execute_query(query, tuple(params), fetch_one=True)
    return result["cnt"] if result else 0


def export_chain(church_id: str, include_hashes: bool = True) -> List[Dict[str, Any]]:
    """Export full audit chain (for backup/analysis).

    Args:
        church_id: Church identifier
        include_hashes: Include hash chain fields (for integrity verification)

    Returns:
        List of all events in chronological order
    """
    church_pk = _resolve_church_pk(church_id)

    if include_hashes:
        query = "SELECT * FROM approval_audit_events WHERE church_id = %s ORDER BY timestamp ASC"
    else:
        query = """SELECT event_id, job_id, line_id, actor_email, actor_role, action,
                          gl_at_action, original_gl, rationale, notes, timestamp
                   FROM approval_audit_events WHERE church_id = %s ORDER BY timestamp ASC"""

    return execute_query(query, (church_pk,), fetch_one=False)
