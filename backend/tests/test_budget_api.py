"""API endpoint tests for budget feature.

Uses a temp DATA_ROOT so tests don't touch real church data.
"""
from __future__ import annotations
import io
import json
import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.models import (
    Account, AccountingContext, BudgetMonth, BudgetPlan,
    DenominationType, Fund, FundCategory, RestrictionClass,
)


# ---------- Fixtures ----------

@pytest.fixture
def tmp_data_root(tmp_path, monkeypatch):
    """Redirect coa_store.DATA_ROOT and CHROMA_DIR into a tmp dir.

    This isolates each test's church-context JSON from real data.
    """
    from backend.tools import coa_store
    new_root = tmp_path / "data"
    new_root.mkdir()
    new_chroma = new_root / "chroma"
    new_chroma.mkdir()

    monkeypatch.setattr(coa_store, "DATA_ROOT", new_root)
    monkeypatch.setattr(coa_store, "CHROMA_DIR", new_chroma)
    monkeypatch.setattr(coa_store, "_chroma_client", None)
    # Disable index rebuild — chroma in tmp is fine but slow
    monkeypatch.setattr(coa_store, "_rebuild_index", lambda ctx: None)
    yield new_root


@pytest.fixture
def seeded_church(tmp_data_root):
    """Save a minimal church context to disk in the tmp data root."""
    from backend.tools import coa_store
    ctx = AccountingContext(
        church_id="testch",
        church_name="Test Church",
        denomination_type=DenominationType.OTHER,
        fiscal_year=2026,
        fiscal_year_start=date(2026, 1, 1),
        accounts=[
            Account(account_number="7100", account_name="Office Supplies",
                    account_type="Expense", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            Account(account_number="7200", account_name="Utilities",
                    account_type="Expense", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
        ],
        funds=[
            Fund(fund_id="GEN", fund_name="General",
                 restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                 fund_category=FundCategory.GENERAL_OPERATING),
        ],
    )
    coa_store.save_accounting_context(ctx)
    return ctx


@pytest.fixture
def client(tmp_data_root):
    from backend.main import app
    return TestClient(app)


def _make_budget_xlsx(rows):
    """rows: list of [account_number, account_name, annual]."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Budget"
    ws.append(["account_number", "account_name", "annual_budget"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- POST /budget/import-spreadsheet ----------

def test_import_budget_spreadsheet_success(client, seeded_church):
    content = _make_budget_xlsx([
        ["7100", "Office Supplies", 24000],
        ["7200", "Utilities", 18000],
    ])
    resp = client.post(
        "/api/churches/testch/budget/import-spreadsheet",
        files={"file": ("budget.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accounts_loaded"] == 2
    assert Decimal(body["annual_total"]) == Decimal("42000")
    assert body["amendment_number"] == 0


def test_import_budget_spreadsheet_unknown_church(client, tmp_data_root):
    content = _make_budget_xlsx([["7100", "Office", 1000]])
    resp = client.post(
        "/api/churches/missing/budget/import-spreadsheet",
        files={"file": ("budget.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 404


def test_import_budget_spreadsheet_bad_extension(client, seeded_church):
    resp = client.post(
        "/api/churches/testch/budget/import-spreadsheet",
        files={"file": ("budget.txt", b"not a spreadsheet", "text/plain")},
    )
    assert resp.status_code == 400


def test_import_budget_spreadsheet_no_budget_columns(client, seeded_church):
    """A sheet with only account_number/account_name (no budget cols) should fail."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Accounts"
    ws.append(["account_number", "account_name", "account_type"])
    ws.append(["7100", "Office", "Expense"])
    buf = io.BytesIO()
    wb.save(buf)
    resp = client.post(
        "/api/churches/testch/budget/import-spreadsheet",
        files={"file": ("a.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 422


def test_import_budget_spreadsheet_unknown_accounts_skipped(client, seeded_church):
    content = _make_budget_xlsx([
        ["7100", "Office", 24000],     # known
        ["9999", "Bogus", 5000],        # unknown — skipped
    ])
    resp = client.post(
        "/api/churches/testch/budget/import-spreadsheet",
        files={"file": ("b.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accounts_loaded"] == 1
    assert any("9999" in w for w in body["warnings"])


def test_import_budget_spreadsheet_all_unknown_accounts(client, seeded_church):
    content = _make_budget_xlsx([["9999", "Bogus", 5000]])
    resp = client.post(
        "/api/churches/testch/budget/import-spreadsheet",
        files={"file": ("b.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 422


def test_import_budget_amendment_increments(client, seeded_church):
    """A second import to the same church increments amendment_number."""
    content = _make_budget_xlsx([["7100", "Office", 24000]])
    r1 = client.post(
        "/api/churches/testch/budget/import-spreadsheet",
        files={"file": ("b.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r1.status_code == 200
    assert r1.json()["amendment_number"] == 0

    r2 = client.post(
        "/api/churches/testch/budget/import-spreadsheet",
        files={"file": ("b.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r2.status_code == 200
    assert r2.json()["amendment_number"] == 1


# ---------- GET /budget ----------

def test_get_budget_unconfigured_returns_404(client, seeded_church):
    resp = client.get("/api/churches/testch/budget")
    assert resp.status_code == 404


def test_get_budget_returns_plan(client, seeded_church):
    content = _make_budget_xlsx([["7100", "Office", 24000]])
    client.post(
        "/api/churches/testch/budget/import-spreadsheet",
        files={"file": ("b.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    resp = client.get("/api/churches/testch/budget")
    assert resp.status_code == 200
    body = resp.json()
    assert body["budget"]["fiscal_year"] == 2026
    assert "7100" in body["budget"]["accounts"]
    assert body["budget_warning_threshold"] == 0.80
    assert body["ytd_actuals"] == {}


def test_get_budget_unknown_church(client, tmp_data_root):
    resp = client.get("/api/churches/missing/budget")
    assert resp.status_code == 404


# ---------- GET /budget/variance-report ----------

def test_variance_report_no_budget_returns_404(client, seeded_church):
    resp = client.get("/api/churches/testch/budget/variance-report")
    assert resp.status_code == 404


def test_variance_report_buckets(client, seeded_church):
    """7100 OVER, 7200 within."""
    from backend.tools import coa_store
    ctx = coa_store.load_accounting_context("testch")
    ctx.budget = BudgetPlan(
        fiscal_year=2026, plan_date=date(2026, 1, 1),
        accounts={
            "7100": BudgetMonth(annual_total=Decimal("100")),
            "7200": BudgetMonth(annual_total=Decimal("1000")),
        },
        uploaded_at=datetime.utcnow(),
    )
    ctx.ytd_actuals = {
        "7100": Decimal("150"),  # over
        "7200": Decimal("100"),  # within
    }
    coa_store.save_accounting_context(ctx)

    resp = client.get("/api/churches/testch/budget/variance-report")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    over_acct_nos = {r["account_number"] for r in body["buckets"]["over"]}
    within_acct_nos = {r["account_number"] for r in body["buckets"]["within"]}
    assert "7100" in over_acct_nos
    assert "7200" in within_acct_nos


def test_variance_report_at_risk(client, seeded_church):
    from backend.tools import coa_store
    ctx = coa_store.load_accounting_context("testch")
    ctx.budget = BudgetPlan(
        fiscal_year=2026, plan_date=date(2026, 1, 1),
        accounts={"7100": BudgetMonth(annual_total=Decimal("1000"))},
        uploaded_at=datetime.utcnow(),
    )
    ctx.ytd_actuals = {"7100": Decimal("850")}  # 85% — at risk
    coa_store.save_accounting_context(ctx)

    resp = client.get("/api/churches/testch/budget/variance-report")
    body = resp.json()
    at_risk_nos = {r["account_number"] for r in body["buckets"]["at_risk"]}
    assert "7100" in at_risk_nos


# ---------- PUT /budget-warning-threshold ----------

def test_set_threshold_valid(client, seeded_church):
    resp = client.put(
        "/api/churches/testch/budget-warning-threshold",
        json={"threshold": 0.90},
    )
    assert resp.status_code == 200
    assert resp.json()["budget_warning_threshold"] == 0.90


def test_set_threshold_out_of_range(client, seeded_church):
    resp = client.put(
        "/api/churches/testch/budget-warning-threshold",
        json={"threshold": 1.5},
    )
    assert resp.status_code == 422


def test_set_threshold_negative(client, seeded_church):
    resp = client.put(
        "/api/churches/testch/budget-warning-threshold",
        json={"threshold": -0.1},
    )
    assert resp.status_code == 422


# ---------- PUT /budget/ytd-reset ----------

def test_ytd_reset_requires_confirm(client, seeded_church):
    resp = client.put(
        "/api/churches/testch/budget/ytd-reset",
        json={"confirm": False, "reset_to_zero": True},
    )
    assert resp.status_code == 400


def test_ytd_reset_zeroes_actuals(client, seeded_church):
    from backend.tools import coa_store
    ctx = coa_store.load_accounting_context("testch")
    ctx.ytd_actuals = {"7100": Decimal("500")}
    coa_store.save_accounting_context(ctx)

    resp = client.put(
        "/api/churches/testch/budget/ytd-reset",
        json={"confirm": True, "reset_to_zero": True},
    )
    assert resp.status_code == 200
    assert Decimal(resp.json()["previous_ytd_total"]) == Decimal("500")

    ctx2 = coa_store.load_accounting_context("testch")
    assert ctx2.ytd_actuals == {}


# ---------- POST /budget/year-end-reset ----------

def test_year_end_reset_requires_confirm(client, seeded_church):
    resp = client.post(
        "/api/churches/testch/budget/year-end-reset",
        json={"next_fiscal_year": 2027, "roll_forward_plan": False, "confirm": False},
    )
    assert resp.status_code == 400


def test_year_end_reset_no_rollforward(client, seeded_church):
    from backend.tools import coa_store
    ctx = coa_store.load_accounting_context("testch")
    ctx.budget = BudgetPlan(
        fiscal_year=2026, plan_date=date(2026, 1, 1),
        accounts={"7100": BudgetMonth(annual_total=Decimal("24000"))},
        uploaded_at=datetime.utcnow(),
    )
    ctx.ytd_actuals = {"7100": Decimal("500")}
    coa_store.save_accounting_context(ctx)

    resp = client.post(
        "/api/churches/testch/budget/year-end-reset",
        json={"next_fiscal_year": 2027, "roll_forward_plan": False, "confirm": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_fiscal_year"] == 2027
    assert body["plan_rolled_forward"] is False

    ctx2 = coa_store.load_accounting_context("testch")
    assert ctx2.fiscal_year == 2027
    assert ctx2.ytd_actuals == {}
    assert ctx2.budget is None


def test_year_end_reset_rollforward(client, seeded_church):
    from backend.tools import coa_store
    ctx = coa_store.load_accounting_context("testch")
    ctx.budget = BudgetPlan(
        fiscal_year=2026, plan_date=date(2026, 1, 1),
        amendment_number=2,
        accounts={"7100": BudgetMonth(annual_total=Decimal("24000"))},
        uploaded_at=datetime.utcnow(),
    )
    ctx.ytd_actuals = {"7100": Decimal("500")}
    coa_store.save_accounting_context(ctx)

    resp = client.post(
        "/api/churches/testch/budget/year-end-reset",
        json={"next_fiscal_year": 2027, "roll_forward_plan": True, "confirm": True},
    )
    assert resp.status_code == 200

    ctx2 = coa_store.load_accounting_context("testch")
    assert ctx2.fiscal_year == 2027
    assert ctx2.ytd_actuals == {}
    assert ctx2.budget is not None
    assert ctx2.budget.fiscal_year == 2027
    assert ctx2.budget.amendment_number == 3
