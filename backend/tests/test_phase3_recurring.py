"""Phase 3.8 — Recurring JEs + CSV batch import (FR-08-recurring)."""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from backend.tests.factories import JournalEntryFactory


def _je_template(amount="100.00"):
    """Return a JournalEntry-shaped dict suitable as a template.

    DEPRECATED: Use JournalEntryFactory.build_recurring_template() instead.
    Kept for backward compatibility with existing tests.
    """
    return JournalEntryFactory.build_recurring_template(
        amount=amount,
        church_id="testch",
        description="Monthly rent",
    )


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main as main_mod

    new_data = tmp_path / "data"
    new_data.mkdir()
    monkeypatch.setattr(main_mod, "JE_DATA_DIR", new_data)
    monkeypatch.setattr(main_mod, "RECURRING_DATA_DIR", new_data, raising=False)
    return TestClient(main_mod.app), new_data


# ---- Schemas ----

def test_recurring_je_schema():
    from backend.models.schemas import RecurringJE
    r = RecurringJE(
        recurring_id="REC-1", church_id="testch",
        template_je=_je_template(), schedule_cron="0 0 1 * *",
    )
    assert r.active is True
    assert r.recurring_id == "REC-1"


# ---- Endpoints ----

def test_create_and_list_recurring_je(api_client):
    client, _ = api_client
    body = {
        "church_id": "testch",
        "template_je": _je_template(),
        "schedule_cron": "0 0 1 * *",
        "created_by": "treasurer@church.org",
    }
    r = client.post("/api/jes/recurring", json=body)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["recurring_id"].startswith("REC-")
    assert rec["active"] is True
    rid = rec["recurring_id"]

    r2 = client.get("/api/jes/recurring", params={"church_id": "testch"})
    assert r2.status_code == 200
    items = r2.json()
    assert any(i["recurring_id"] == rid for i in items)


def test_update_and_deactivate_recurring(api_client):
    client, _ = api_client
    body = {
        "church_id": "testch",
        "template_je": _je_template(),
        "schedule_cron": "0 0 15 * *",
    }
    r = client.post("/api/jes/recurring", json=body)
    rid = r.json()["recurring_id"]

    r2 = client.put(f"/api/jes/recurring/{rid}", json={"schedule_cron": "0 0 1 * *"})
    assert r2.status_code == 200
    assert r2.json()["schedule_cron"] == "0 0 1 * *"

    r3 = client.delete(f"/api/jes/recurring/{rid}")
    assert r3.status_code == 200
    assert r3.json()["ok"] is True


def test_csv_batch_import(api_client):
    client, data_dir = api_client
    csv_text = (
        "memo,from_account,to_account,amount,fund\n"
        "Rent May,7100,2010,500.00,GEN\n"
        "Insurance,7150,2010,250.50,GEN\n"
        "Utilities,7200,2010,125.00,GEN\n"
    )
    files = {"file": ("entries.csv", csv_text, "text/csv")}
    r = client.post(
        "/api/jes/import-csv",
        data={"church_id": "testch"},
        files=files,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["drafted_count"] == 3
    assert body["errors"] == []
    # Verify JEs were persisted
    je_file = data_dir / "jes_testch.jsonl"
    assert je_file.exists()
    lines = [json.loads(l) for l in je_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 3
    assert all(l["status"] == "DRAFT" for l in lines)


def test_csv_import_handles_bad_rows(api_client):
    client, _ = api_client
    csv_text = (
        "memo,from_account,to_account,amount,fund\n"
        "Good row,7100,2010,500.00,GEN\n"
        ",,,abc,GEN\n"  # invalid amount + missing accts
        "Another good,7100,2010,200.00,GEN\n"
    )
    files = {"file": ("entries.csv", csv_text, "text/csv")}
    r = client.post(
        "/api/jes/import-csv",
        data={"church_id": "testch"},
        files=files,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["drafted_count"] == 2
    assert len(body["errors"]) == 1


# ---- Scheduler job ----

def test_scheduler_drafts_recurring_je(tmp_path, monkeypatch):
    from backend import scheduler as sched_mod
    # Redirect scheduler's data_dir lookup by patching Path resolution via env.
    # Simpler: write a recurring file to the real data dir, run, clean up.
    real_data = Path(sched_mod.__file__).resolve().parent / "data"
    real_data.mkdir(parents=True, exist_ok=True)
    cid = f"sched_test_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    rec = {
        "recurring_id": f"REC-{cid}",
        "church_id": cid,
        "template_je": _je_template(),
        "schedule_cron": "0 0 1 * *",
        "active": True,
        "next_run": None,
    }
    rec_file = real_data / f"recurring_{cid}.jsonl"
    rec_file.write_text(json.dumps(rec) + "\n")

    try:
        sched_mod.draft_recurring_jes()
        je_file = real_data / f"jes_{cid}.jsonl"
        assert je_file.exists(), "scheduler did not draft a JE"
        drafted = [
            json.loads(l) for l in je_file.read_text().splitlines() if l.strip()
        ]
        assert len(drafted) >= 1
        assert drafted[0]["status"] == "DRAFT"
        assert drafted[0]["entry_id"].startswith("REC-")
    finally:
        if rec_file.exists():
            rec_file.unlink()
        je_file = real_data / f"jes_{cid}.jsonl"
        if je_file.exists():
            je_file.unlink()
