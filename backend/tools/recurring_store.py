"""Recurring JE store (FR-08-recurring / Phase 3.8).

CRUD helpers for recurring journal-entry schedules persisted as JSONL files
at ``backend/data/recurring_{church_id}.jsonl``. Each call to
``save_recurring_entries`` rewrites the whole file in compact form (one
record per line, last-writer-wins on ``recurring_id``). The scheduler in
``backend/scheduler.py`` reads the same files.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.schemas import JournalEntry, RecurringJE

logger = logging.getLogger("eime.recurring_store")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _safe(church_id: str) -> str:
    return "".join(c for c in church_id if c.isalnum() or c in "_-") or "default"


def _path(church_id: str) -> Path:
    return DATA_DIR / f"recurring_{_safe(church_id)}.jsonl"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _calculate_next_cron(cron_expr: str, from_time: Optional[datetime] = None) -> Optional[datetime]:
    """Compute the next firing of a 5-field cron expression.

    Falls back to ``None`` if the croniter library is unavailable so callers
    can still persist a schedule even in minimal environments.
    """
    base = from_time or _utcnow()
    try:
        from croniter import croniter  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - optional dep
        logger.warning("croniter not installed — next_run left as None")
        return None
    try:
        c = croniter(cron_expr, base)
        nxt = c.get_next(datetime)
        if isinstance(nxt, datetime):
            return nxt
        # Fallback: croniter returned a unix timestamp.
        return datetime.fromtimestamp(float(nxt), tz=timezone.utc)
    except Exception as e:  # pragma: no cover - bad cron strings
        logger.warning(f"Invalid cron '{cron_expr}': {e}")
        return None


def calculate_next_cron(cron_expr: str, from_time: Optional[datetime] = None) -> Optional[datetime]:
    """Public alias used by the scheduler & API endpoints."""
    return _calculate_next_cron(cron_expr, from_time)


def load_recurring_entries(church_id: str) -> List[RecurringJE]:
    """Load all recurring entries for a church (last write wins per id)."""
    p = _path(church_id)
    if not p.exists():
        return []
    by_id: Dict[str, Dict[str, Any]] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = d.get("recurring_id")
        if rid:
            by_id[rid] = d
    out: List[RecurringJE] = []
    for d in by_id.values():
        try:
            out.append(RecurringJE(**d))
        except Exception as e:
            logger.warning(f"Bad recurring row for {church_id}: {e}")
    return out


def save_recurring_entries(church_id: str, entries: List[RecurringJE]) -> None:
    """Rewrite the recurring file with the given entries (one per line)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(church_id)
    with p.open("w", encoding="utf-8") as f:
        for r in entries:
            f.write(json.dumps(r.model_dump(), default=str) + "\n")


def find_recurring(church_id: str, recurring_id: str) -> Optional[RecurringJE]:
    for r in load_recurring_entries(church_id):
        if r.recurring_id == recurring_id:
            return r
    return None


def create_recurring(
    church_id: str,
    template_je: JournalEntry | Dict[str, Any],
    cron: str,
    created_by: Optional[str] = None,
    active: bool = True,
) -> RecurringJE:
    """Create + persist a new recurring schedule, returning the model."""
    if isinstance(template_je, JournalEntry):
        tpl_dict = template_je.model_dump()
    else:
        # Validate it round-trips through the JournalEntry model.
        tpl_dict = JournalEntry(**template_je).model_dump()
    now = _utcnow()
    rec = RecurringJE(
        recurring_id=f"REC-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
        church_id=church_id,
        template_je=tpl_dict,
        schedule_cron=cron,
        active=active,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        next_run=_calculate_next_cron(cron, now),
        draft_count=0,
    )
    entries = load_recurring_entries(church_id)
    entries.append(rec)
    save_recurring_entries(church_id, entries)
    return rec


def update_recurring(church_id: str, recurring: RecurringJE) -> RecurringJE:
    """Replace the matching record by id (creating it if missing)."""
    recurring.updated_at = _utcnow()
    entries = load_recurring_entries(church_id)
    replaced = False
    for i, r in enumerate(entries):
        if r.recurring_id == recurring.recurring_id:
            entries[i] = recurring
            replaced = True
            break
    if not replaced:
        entries.append(recurring)
    save_recurring_entries(church_id, entries)
    return recurring


def delete_recurring(church_id: str, recurring_id: str) -> bool:
    entries = load_recurring_entries(church_id)
    new_entries = [r for r in entries if r.recurring_id != recurring_id]
    if len(new_entries) == len(entries):
        return False
    save_recurring_entries(church_id, new_entries)
    return True


def get_due_for_drafting(church_id: str, now: Optional[datetime] = None) -> List[RecurringJE]:
    """Return all active entries whose ``next_run`` is in the past or null."""
    now = now or _utcnow()
    due: List[RecurringJE] = []
    for r in load_recurring_entries(church_id):
        if not r.active:
            continue
        if r.next_run is None:
            due.append(r)
            continue
        nr = r.next_run
        # Normalize naive → UTC for comparison.
        if nr.tzinfo is None:
            nr = nr.replace(tzinfo=timezone.utc)
        if nr <= now:
            due.append(r)
    return due


def list_all_church_ids() -> List[str]:
    """Discover every church_id that currently has a recurring file."""
    if not DATA_DIR.exists():
        return []
    return sorted(
        f.stem.replace("recurring_", "") for f in DATA_DIR.glob("recurring_*.jsonl")
    )
