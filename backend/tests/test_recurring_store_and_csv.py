"""Phase 3.8 — coverage for the new helper modules.

Exercises ``backend/tools/recurring_store.py`` (CRUD + cron), and
``backend/tools/je_csv_importer.py`` (parse + persist + validation paths)
in isolation from the FastAPI layer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _je_template():
    return {
        "entry_id": "TPL-XYZ",
        "church_id": "tch",
        "fiscal_year": 2026,
        "accounting_period": "2026-05",
        "entry_date": "2026-05-06",
        "reference": "TPL",
        "vendor_name": "Vendor",
        "description": "Recurring",
        "status": "DRAFT",
        "lines": [
            {
                "sequence": 1, "account_number": "7100",
                "account_name": "Office", "fund_id": "GEN",
                "fund_name": "General", "debit": "100", "credit": "0",
                "memo": "x",
            },
            {
                "sequence": 2, "account_number": "2010",
                "account_name": "AP", "fund_id": "GEN",
                "fund_name": "General", "debit": "0", "credit": "100",
                "memo": "x",
            },
        ],
        "total_debits": "100",
        "total_credits": "100",
        "balanced": True,
    }


# ---------- recurring_store ----------

def test_calculate_next_cron_returns_future(monkeypatch):
    from backend.tools import recurring_store as rs
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    nxt = rs.calculate_next_cron("0 2 1 * *", base)
    assert nxt is not None
    # First-of-month at 02:00 after Jan 1 00:00 → Jan 1 02:00 same day.
    assert nxt.month == 1 and nxt.hour == 2


def test_create_load_update_delete_recurring(tmp_path, monkeypatch):
    from backend.tools import recurring_store as rs
    monkeypatch.setattr(rs, "DATA_DIR", tmp_path)

    rec = rs.create_recurring(
        church_id="tch",
        template_je=_je_template(),
        cron="0 2 1 * *",
        created_by="t@x.org",
    )
    assert rec.recurring_id.startswith("REC-")
    assert rec.draft_count == 0
    assert rec.next_run is not None  # croniter installed → populated

    # Load
    loaded = rs.load_recurring_entries("tch")
    assert len(loaded) == 1
    assert loaded[0].recurring_id == rec.recurring_id

    # Update
    rec.active = False
    rec.schedule_cron = "0 3 1 * *"
    rs.update_recurring("tch", rec)
    again = rs.find_recurring("tch", rec.recurring_id)
    assert again is not None
    assert again.active is False
    assert again.schedule_cron == "0 3 1 * *"

    # Delete
    assert rs.delete_recurring("tch", rec.recurring_id) is True
    assert rs.find_recurring("tch", rec.recurring_id) is None
    assert rs.delete_recurring("tch", rec.recurring_id) is False  # already gone


def test_get_due_for_drafting(tmp_path, monkeypatch):
    from backend.tools import recurring_store as rs
    monkeypatch.setattr(rs, "DATA_DIR", tmp_path)

    rec = rs.create_recurring("tch", _je_template(), "0 2 1 * *")
    # Force next_run into the past.
    rec.next_run = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rs.update_recurring("tch", rec)

    due = rs.get_due_for_drafting("tch")
    assert any(r.recurring_id == rec.recurring_id for r in due)

    # Inactive → not due
    rec.active = False
    rs.update_recurring("tch", rec)
    due2 = rs.get_due_for_drafting("tch")
    assert not any(r.recurring_id == rec.recurring_id for r in due2)


# ---------- je_csv_importer ----------

def test_parse_je_csv_happy_path(tmp_path):
    from backend.tools.je_csv_importer import parse_je_csv
    csv_text = (
        "memo,from_account,to_account,amount,fund\n"
        "Rent,7100,2010,500,GEN\n"
        "Utilities,7200,2010,250.50,GEN\n"
    ).encode()
    jes, result = parse_je_csv(csv_text, "tch")
    assert result.drafted_count == 2
    assert result.failed_count == 0
    assert len(jes) == 2
    assert all(j.status.value == "DRAFT" for j in jes)


def test_parse_je_csv_missing_column():
    from backend.tools.je_csv_importer import parse_je_csv
    csv_text = b"memo,from_account,to_account,amount\nfoo,7100,2010,5\n"  # no 'fund'
    jes, result = parse_je_csv(csv_text, "tch")
    assert jes == []
    assert any("fund" in e for e in result.errors)


def test_parse_je_csv_bad_amount():
    from backend.tools.je_csv_importer import parse_je_csv
    csv_text = (
        "memo,from_account,to_account,amount,fund\n"
        "Bad,7100,2010,abc,GEN\n"
        "Good,7100,2010,10,GEN\n"
    ).encode()
    jes, result = parse_je_csv(csv_text, "tch")
    assert result.drafted_count == 1
    assert result.failed_count == 1
    assert "Row 2" in result.errors[0]


def test_import_je_csv_persists(tmp_path):
    from backend.tools.je_csv_importer import import_je_csv
    csv_text = (
        "memo,from_account,to_account,amount,fund\n"
        "Rent,7100,2010,500,GEN\n"
    ).encode()
    res = import_je_csv(csv_text, "ttest", data_dir=tmp_path)
    assert res.drafted_count == 1
    files = list(tmp_path.glob("jes_ttest.jsonl"))
    assert len(files) == 1
    rows = [
        json.loads(l) for l in files[0].read_text().splitlines() if l.strip()
    ]
    assert rows[0]["status"] == "DRAFT"
    assert rows[0]["entry_id"].startswith("CSV-")


def test_import_je_csv_with_optional_date(tmp_path):
    from backend.tools.je_csv_importer import import_je_csv
    csv_text = (
        "memo,from_account,to_account,amount,fund,date\n"
        "Backdated,7100,2010,250,GEN,2026-01-15\n"
    ).encode()
    res = import_je_csv(csv_text, "tch", data_dir=tmp_path)
    assert res.drafted_count == 1
    rows = [
        json.loads(l)
        for l in (tmp_path / "jes_tch.jsonl").read_text().splitlines()
        if l.strip()
    ]
    assert rows[0]["entry_date"] == "2026-01-15"
    assert rows[0]["accounting_period"] == "2026-01"
