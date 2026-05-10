"""FR-05.5: APScheduler-driven reminder + escalation worker.

Runs hourly, scans every job in PENDING_BUDGET_OWNER, and:
  - sends a reminder email if `hours_pending > deadline_hours` and no reminder
    has been sent in the last `deadline_hours` window
  - escalates to the secondary approver (treasurer) if
    `business_days_pending > escalation_days`

Escalation transitions the job to PENDING_TREASURER and notifies the
secondary approver via email.

The scheduler degrades gracefully if APScheduler is not installed (logs a
warning and becomes a no-op) so dev environments without the package boot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger("eime.scheduler")

try:  # pragma: no cover - import-time guard
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.jobstores.memory import MemoryJobStore
    _APS_AVAILABLE = True
except Exception:  # pragma: no cover
    BackgroundScheduler = None  # type: ignore[assignment]
    MemoryJobStore = None  # type: ignore[assignment]
    _APS_AVAILABLE = False


_scheduler: Optional[Any] = None


def _business_days_between(start: datetime, end: datetime) -> int:
    """Inclusive count of weekdays between start and end (rough)."""
    if end < start:
        return 0
    days = 0
    cur = start.date()
    last = end.date()
    while cur <= last:
        if cur.weekday() < 5:  # Mon=0, Sun=6
            days += 1
        cur = cur + timedelta(days=1)
    # Subtract one so a same-day call returns 0 elapsed business days.
    return max(0, days - 1)


def check_pending_approvals() -> None:
    """Hourly job: scan jobs, send reminders, escalate."""
    # Local imports to avoid circular import at module load time.
    from . import flow
    from .models.schemas import ProcessingStatus
    from .tools.approval_chain_resolver import find_chain_for_gl
    from .integrations.email.smtp_sender import send_email
    from .tools.approval_audit import append_event

    now = datetime.utcnow()
    for job in flow.list_jobs():
        if job.status != ProcessingStatus.PENDING_BUDGET_OWNER:
            continue
        started = job.pending_approval_started_at or job.updated_at
        if not started:
            continue
        hours_pending = (now - started).total_seconds() / 3600.0
        business_days = _business_days_between(started, now)

        chain = None
        if job.approval_chain_id:
            for c in _load_all_chains_for_job(job):
                if c.chain_id == job.approval_chain_id:
                    chain = c
                    break

        deadline_hours = chain.deadline_hours if chain else 48
        escalation_days = chain.escalation_days if chain else 5

        # ---- Reminder ----
        if hours_pending > deadline_hours:
            recent = [
                r for r in (job.reminders_sent or [])
                if r.get("kind") == "REMINDER"
                and (now - datetime.fromisoformat(r["ts"])).total_seconds() / 3600.0
                    < deadline_hours
            ]
            if not recent and chain and job.pending_approval_email:
                subject = f"Reminder: approval pending — {job.filename}"
                body = (
                    f"<p>Reminder: invoice {job.filename} has been pending "
                    f"your approval for {hours_pending:.0f} hours.</p>"
                )
                send_email(job.pending_approval_email, subject, body)
                job.reminders_sent.append({
                    "kind": "REMINDER",
                    "ts": now.isoformat(),
                    "to": job.pending_approval_email,
                })
                append_event(job.church_id, {
                    "job_id": job.job_id,
                    "actor_email": "system@eime",
                    "actor_role": "scheduler",
                    "action": "REMINDER_SENT",
                    "notes": f"Reminder sent after {hours_pending:.0f}h",
                })

        # ---- Escalation ----
        if business_days > escalation_days and chain:
            already = any(
                r.get("kind") == "ESCALATION" for r in (job.reminders_sent or [])
            )
            if not already:
                subject = f"Escalation: approval overdue — {job.filename}"
                body = (
                    f"<p>Invoice {job.filename} has been pending budget-owner "
                    f"approval for {business_days} business days. "
                    f"Escalating to treasurer for review.</p>"
                )
                send_email(chain.secondary_approver_email, subject, body)
                job.reminders_sent.append({
                    "kind": "ESCALATION",
                    "ts": now.isoformat(),
                    "to": chain.secondary_approver_email,
                })
                # Move to treasurer queue.
                job.status = ProcessingStatus.PENDING_TREASURER
                job.updated_at = now
                job.audit_log.append({
                    "ts": now.isoformat(),
                    "event_type": "ESCALATION",
                    "status": ProcessingStatus.PENDING_TREASURER.value,
                    "detail": (
                        f"Auto-escalated to treasurer after "
                        f"{business_days} business days"
                    ),
                })
                append_event(job.church_id, {
                    "job_id": job.job_id,
                    "actor_email": "system@eime",
                    "actor_role": "scheduler",
                    "action": "ESCALATED_TO_TREASURER",
                    "notes": f"After {business_days} business days",
                })


def _load_all_chains_for_job(job: Any) -> list:
    from .tools.approval_chain_resolver import load_chains
    return load_chains(job.church_id)


def draft_recurring_jes() -> None:
    """FR-08-recurring: nightly job that drafts recurring JEs whose schedule has fired.

    Reads `backend/data/recurring_*.jsonl`, filters active rows whose
    `next_run` is in the past (or None), and persists a fresh DRAFT JE
    derived from the template_je. Updates last_drafted_at.
    """
    import json
    from datetime import datetime as _dt
    from pathlib import Path
    from .models.schemas import JournalEntry, JEStatus

    data_dir = Path(__file__).resolve().parent / "data"
    if not data_dir.exists():
        return

    now = _dt.utcnow()
    for f in data_dir.glob("recurring_*.jsonl"):
        cid = f.stem.replace("recurring_", "")
        # Read latest record per recurring_id.
        by_id: dict = {}
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("recurring_id"):
                by_id[d["recurring_id"]] = d

        for rec in by_id.values():
            if not rec.get("active"):
                continue
            nr = rec.get("next_run")
            if nr:
                try:
                    next_dt = _dt.fromisoformat(str(nr).replace("Z", ""))
                    if next_dt > now:
                        continue
                except Exception:
                    pass

            template = rec.get("template_je") or {}
            try:
                tpl_je = JournalEntry(**template)
            except Exception as e:
                logger.warning(f"Recurring {rec.get('recurring_id')} bad template: {e}")
                continue

            # Clone with fresh entry_id and DRAFT status
            tpl = tpl_je.model_dump()
            tpl["entry_id"] = f"REC-{rec['recurring_id']}-{now.strftime('%Y%m%d%H%M%S')}"
            tpl["status"] = JEStatus.DRAFT.value
            tpl["entry_date"] = now.date().isoformat()
            tpl["accounting_period"] = now.strftime("%Y-%m")

            # Append to JE store
            jes_path = data_dir / f"jes_{cid}.jsonl"
            with jes_path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(tpl, default=str) + "\n")

            # Update recurring row: bump count + advance next_run via cron lib.
            rec["last_drafted_at"] = now.isoformat()
            rec["draft_count"] = int(rec.get("draft_count", 0) or 0) + 1
            try:
                from .tools.recurring_store import calculate_next_cron
                nxt = calculate_next_cron(str(rec.get("schedule_cron", "")), now)
                rec["next_run"] = nxt.isoformat() if nxt else None
            except Exception:  # pragma: no cover
                rec["next_run"] = None
            with f.open("a", encoding="utf-8") as out:
                out.write(json.dumps(rec, default=str) + "\n")

            logger.info(
                f"Drafted recurring JE {tpl['entry_id']} for {cid} "
                f"(rec={rec['recurring_id']})"
            )


def sync_all_plaid_accounts() -> None:
    """Phase 5c: Continuous Plaid sync background job (every 30 minutes).

    Syncs Plaid transactions for all churches without UI intervention.
    Runs automatically; structural matching happens on each sync.
    """
    try:
        from .db import connection, plaid_store

        # Load all churches
        rows = connection.execute_query("SELECT church_id FROM churches") or []
        for row in rows:
            church_id = row.get("church_id")
            if not church_id:
                continue
            try:
                # Get all Plaid accounts for this church
                accounts = plaid_store.load_plaid_accounts(church_id)
                for account in accounts:
                    try:
                        new_txns = plaid_store.fetch_and_store_transactions(
                            church_id,
                            account.get("account_id") or "",
                            days_back=60
                        )
                        logger.info(
                            f"Plaid sync: {church_id} / {account.get('account_id')} "
                            f"synced {len(new_txns)} transactions"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Plaid sync failed for {church_id} / "
                            f"{account.get('account_id')}: {e}"
                        )
            except Exception as e:
                logger.warning(f"Plaid sync failed for {church_id}: {e}")
    except Exception as e:
        logger.error(f"Plaid background sync job error: {e}")


def start_scheduler() -> None:
    """Start the background scheduler. No-op if APScheduler unavailable."""
    global _scheduler
    if not _APS_AVAILABLE:
        logger.warning("APScheduler not installed — reminder worker disabled")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(jobstores={"default": MemoryJobStore()})
    _scheduler.add_job(
        check_pending_approvals,
        "cron",
        hour="*",
        id="approval_check",
        replace_existing=True,
    )
    # Recurring JE nightly draft at 02:00.
    _scheduler.add_job(
        draft_recurring_jes,
        "cron",
        hour="2",
        minute="0",
        id="recurring_je_draft",
        replace_existing=True,
    )
    # Plaid background sync every 30 minutes (Phase 5c: continuous reconciliation).
    _scheduler.add_job(
        sync_all_plaid_accounts,
        "interval",
        minutes=30,
        id="plaid_sync",
        replace_existing=True,
    )
    _scheduler.start()


def shutdown_scheduler() -> None:
    """Stop the background scheduler cleanly."""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        pass
    _scheduler = None
