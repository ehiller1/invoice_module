"""Event emission infrastructure.

Two entry points:
  - emit_event(...)         — opens its own atomic transaction
  - emit_event_in_txn(conn) — joins an existing transaction (preferred when
                              the event must be atomic with another DB write)

Both serialize the event envelope to the `events` table and the tag list
to `event_tags`. JSON serialization preserves Decimal as string via
mode="json".
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Optional
from uuid import UUID

from psycopg2.extras import Json

from ..db.connection import execute_query
from ..db.transactions import atomic_transaction
from .schemas import FinancialEvent


def _resolve_church_pk(church_id: str) -> int:
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _insert_event(cur, event: FinancialEvent, church_pk: int) -> None:
    """Insert one event + its tags using the given cursor (caller commits)."""
    payload_json = event.model_dump(mode="json").get("payload", {})
    caused_by = [str(eid) for eid in event.caused_by]

    cur.execute(
        """
        INSERT INTO events (
            event_id, event_type, church_id, occurred_at,
            actor, confidence, payload, caused_by, correlation_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(event.event_id),
            event.event_type.value,
            church_pk,
            event.occurred_at,
            event.actor,
            event.confidence,
            Json(payload_json),
            Json(caused_by) if caused_by else None,
            event.correlation_id,
        ),
    )

    if event.tags:
        cur.executemany(
            """
            INSERT INTO event_tags (event_id, tag_kind, tag_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (event_id, tag_kind, tag_value) DO NOTHING
            """,
            [
                (str(event.event_id), t.tag_kind.value, t.tag_value)
                for t in event.tags
            ],
        )


def emit_event_in_txn(conn, event: FinancialEvent) -> UUID:
    """Emit an event inside an already-open transaction. The caller commits.

    Use this when the event must be atomic with another write (e.g. a JE
    insert) so that either both succeed or both roll back.
    """
    church_pk = _resolve_church_pk(event.church_id)
    cur = conn.cursor()
    try:
        _insert_event(cur, event, church_pk)
    finally:
        cur.close()
    return event.event_id


def emit_event(event: FinancialEvent) -> UUID:
    """Emit an event in its own atomic transaction.

    Use this for standalone emissions (e.g. background structural matcher)
    where there is no parent transaction to join.
    """
    church_pk = _resolve_church_pk(event.church_id)
    with atomic_transaction() as conn:
        cur = conn.cursor()
        try:
            _insert_event(cur, event, church_pk)
        finally:
            cur.close()
    return event.event_id
