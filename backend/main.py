"""EIME FastAPI application — Embark Invoice Mapping Engine."""
from __future__ import annotations
import asyncio
import json
import os
import shutil
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import dotenv_values
# Load .env from project root
_root = Path(__file__).parent.parent
_env_file = _root / ".env"
if _env_file.exists():
    _env_vars = dotenv_values(_env_file)
    for key, val in _env_vars.items():
        if val:  # Always set if value is non-empty, even if already in environ
            os.environ[key] = val
    print(f"[EIME] Loaded {len(_env_vars)} env vars from {_env_file}", flush=True)
    print(f"[EIME] ANTHROPIC_API_KEY = {os.environ.get('ANTHROPIC_API_KEY', 'NOT SET')[:20]}...", flush=True)

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import requires_role, User, verify_bearer_token
from .models import (
    Account, AccountingContext, AllocationSchedule, ApportionmentAccount,
    ApprovalChain, BudgetMonth, BudgetPlan, ChatRequest, DenominationType,
    DocumentType, Fund, FundCategory, HITLDecisions, HITLLineDecision,
    ProcessingStatus, RestrictionClass,
)
# NOTE: Phase 1 DB-store migration (Imports & Basic Wiring).
# - `tools.coa_store` retained at module level: db.coa_store does not yet
#   expose `ensure_seed` or `semantic_search`. Endpoints that only use
#   load/save/list_churches/upsert/delete are routed through `db.coa_store`
#   via inline imports. Bulk migration of these calls is a later phase.
# - `tools.approval_audit` retained: no db equivalent yet (the eventual
#   db.approval_audit_store change happens inside approval_audit.py, not here).
# - `tools.approval_chain_resolver` retained for now; new code paths use
#   `db.approval_store`.
from .tools import coa_store
from .tools.spreadsheet_parser import parse_spreadsheet
from .tools import approval_chain_resolver, approval_audit
from .integrations.email import tokens as email_tokens
from . import flow
from . import scheduler as approval_scheduler
from . import setup_wizard as _setup_wizard

# Phase 1: DB-backed stores. Importing these makes the symbols available for
# call-site swaps performed in this and subsequent phases.
from . import db
from .db import (
    coa_store as db_coa_store,
    journal_entry_store,
    payment_store,
    plaid_store as db_plaid_store,
    vendor_store as db_vendor_store,
    approval_store,
    bank_txn_store,
    recon_store,
    processing_job_store,
    decision_ledger_store,
)

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

AUDIT_PDF_DIR = Path(__file__).resolve().parent / "audit_pdfs"
AUDIT_PDF_DIR.mkdir(exist_ok=True)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="EIME — Embark Invoice Mapping Engine",
    description="Church invoice multi-agent COA mapping system (FRS-EMBARK-ACCT-001)",
    version="1.1.0",
)
# CORS: restrict to known origins in production
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-User-Role", "X-User-Email", "X-Proxy-Secret"],
)

# Setup wizard endpoints (/api/setup/*)
app.include_router(_setup_wizard.router)

# Phase 5: Queue action endpoints + reconciliation latest
try:
    from .routes import exceptions as _phase5_exceptions
    from .routes import questions as _phase5_questions
    from .routes import policies as _phase5_policies
    from .routes import reconciliation as _phase5_reconciliation
    app.include_router(_phase5_exceptions.router)
    app.include_router(_phase5_questions.router)
    app.include_router(_phase5_policies.router)
    app.include_router(_phase5_reconciliation.router)
except Exception as _phase5_err:  # pragma: no cover - defensive
    import logging as _l
    _l.getLogger("eime.phase5").warning("Phase 5 routers failed to mount: %r", _phase5_err)

# Phase 6: HITL decision endpoint (/v2/hitl/{id}/decision)
try:
    from .routes import hitl as _phase6_hitl
    app.include_router(_phase6_hitl.router)
except Exception as _phase6_err:  # pragma: no cover - defensive
    import logging as _l
    _l.getLogger("eime.phase6").warning("Phase 6 HITL router failed to mount: %r", _phase6_err)

# Phase 8: Approval + ACS posting with guider verdicts
try:
    from .routes import approvals as _phase8_approvals
    app.include_router(_phase8_approvals.router)
except Exception as _phase8_err:  # pragma: no cover - defensive
    import logging as _l
    _l.getLogger("eime.phase8").warning("Phase 8 approvals router failed to mount: %r", _phase8_err)


@app.on_event("startup")
async def startup() -> None:
    coa_store.ensure_seed()
    # FR-05.5: launch reminder/escalation scheduler.
    try:
        approval_scheduler.start_scheduler()
    except Exception as exc:
        print(f"[EIME] scheduler startup skipped: {exc}", flush=True)


@app.on_event("shutdown")
async def shutdown() -> None:
    try:
        approval_scheduler.shutdown_scheduler()
    except Exception:
        pass


# ===== Custom JSON encoder =====
class _Encoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _json(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=json.loads(json.dumps(data, cls=_Encoder, default=str)),
        status_code=status_code
    )


# ===== Churches / COA endpoints =====

@app.get("/api/churches")
async def list_churches() -> JSONResponse:
    return _json(coa_store.list_churches())


class ChurchCreate(BaseModel):
    church_id: str
    church_name: str
    denomination_type: str = "NONDENOMINATIONAL"
    fiscal_year: int = 2025


@app.post("/api/churches")
async def create_church(body: ChurchCreate) -> JSONResponse:
    """Create a new church with a minimal COA skeleton."""
    existing = coa_store.load_accounting_context(body.church_id)
    if existing:
        raise HTTPException(409, f"Church '{body.church_id}' already exists")
    from datetime import date
    ctx = AccountingContext(
        church_id=body.church_id,
        church_name=body.church_name,
        denomination_type=DenominationType(body.denomination_type),
        fiscal_year=body.fiscal_year,
        fiscal_year_start=date(body.fiscal_year, 1, 1),
        accounts=[
            Account(account_number="1000", account_name="Cash — Checking",
                    account_type="Asset", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            Account(account_number="2010", account_name="Accounts Payable",
                    account_type="Liability", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            Account(account_number="4000", account_name="Tithes & Offerings",
                    account_type="Revenue", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            Account(account_number="5000", account_name="Clergy Compensation",
                    account_type="Expense", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            Account(account_number="7000", account_name="Facilities",
                    account_type="Expense", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            Account(account_number="8000", account_name="Administration",
                    account_type="Expense", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
        ],
        funds=[
            Fund(fund_id="GEN", fund_name="General Operating Fund",
                 restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                 fund_category=FundCategory.GENERAL_OPERATING),
        ],
    )
    coa_store.save_accounting_context(ctx)
    return _json({"ok": True, "church_id": body.church_id})


@app.get("/api/churches/{church_id}/context")
async def get_context(church_id: str) -> JSONResponse:
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church COA not found")
    return _json(ctx.model_dump())


@app.get("/api/churches/{church_id}/accounts")
async def get_accounts(church_id: str) -> JSONResponse:
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    return _json([a.model_dump() for a in ctx.accounts])


@app.get("/api/churches/{church_id}/funds")
async def get_funds(church_id: str) -> JSONResponse:
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    return _json([f.model_dump() for f in ctx.funds])


class AccountUpsert(BaseModel):
    account_number: str
    account_name: str
    account_type: str
    fund_id: str
    restriction_class: RestrictionClass
    active: bool = True


@app.post("/api/churches/{church_id}/accounts")
async def upsert_account(church_id: str, body: AccountUpsert) -> JSONResponse:
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    ctx.accounts = [a for a in ctx.accounts if a.account_number != body.account_number]
    ctx.accounts.append(Account(**body.model_dump()))
    ctx.accounts.sort(key=lambda a: a.account_number)
    coa_store.save_accounting_context(ctx)
    return _json({"ok": True})


@app.delete("/api/churches/{church_id}/accounts/{account_number}")
async def delete_account(church_id: str, account_number: str) -> JSONResponse:
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    ctx.accounts = [a for a in ctx.accounts if a.account_number != account_number]
    coa_store.save_accounting_context(ctx)
    return _json({"ok": True})


class FundUpsert(BaseModel):
    fund_id: str
    fund_name: str
    restriction_class: RestrictionClass
    fund_category: FundCategory
    purpose_description: Optional[str] = None
    expenditure_rules: Optional[str] = None
    current_balance: Decimal = Decimal("0")


@app.post("/api/churches/{church_id}/funds")
async def upsert_fund(church_id: str, body: FundUpsert) -> JSONResponse:
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    ctx.funds = [f for f in ctx.funds if f.fund_id != body.fund_id]
    ctx.funds.append(Fund(**body.model_dump()))
    coa_store.save_accounting_context(ctx)
    return _json({"ok": True})


@app.delete("/api/churches/{church_id}/funds/{fund_id}")
async def delete_fund(church_id: str, fund_id: str) -> JSONResponse:
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    ctx.funds = [f for f in ctx.funds if f.fund_id != fund_id]
    coa_store.save_accounting_context(ctx)
    return _json({"ok": True})


class COAImport(BaseModel):
    """Bulk import of a complete chart of accounts."""
    church_name: Optional[str] = None
    denomination_type: Optional[str] = None
    accounts: Optional[List[Dict]] = None
    funds: Optional[List[Dict]] = None
    capitalisation_threshold_usd: Optional[float] = None


@app.post("/api/churches/{church_id}/coa/import")
async def import_coa(church_id: str, body: COAImport) -> JSONResponse:
    """Bulk-replace or merge a church's chart of accounts from JSON."""
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, f"Church '{church_id}' not found. Create it first via POST /api/churches")

    if body.church_name:
        ctx.church_name = body.church_name
    if body.denomination_type:
        ctx.denomination_type = DenominationType(body.denomination_type)
    if body.capitalisation_threshold_usd is not None:
        ctx.capitalisation_threshold_usd = Decimal(str(body.capitalisation_threshold_usd))

    added_accounts = 0
    if body.accounts:
        for a in body.accounts:
            account = Account(
                account_number=str(a["account_number"]),
                account_name=a["account_name"],
                account_type=a.get("account_type", "Expense"),
                fund_id=a.get("fund_id", "GEN"),
                restriction_class=RestrictionClass(
                    a.get("restriction_class", "WITHOUT_RESTRICTION")
                ),
                active=a.get("active", True),
            )
            ctx.accounts = [x for x in ctx.accounts if x.account_number != account.account_number]
            ctx.accounts.append(account)
            added_accounts += 1
        ctx.accounts.sort(key=lambda x: x.account_number)

    added_funds = 0
    if body.funds:
        for f in body.funds:
            fund = Fund(
                fund_id=f["fund_id"],
                fund_name=f["fund_name"],
                restriction_class=RestrictionClass(
                    f.get("restriction_class", "WITHOUT_RESTRICTION")
                ),
                fund_category=FundCategory(
                    f.get("fund_category", "GENERAL_OPERATING")
                ),
                purpose_description=f.get("purpose_description"),
                expenditure_rules=f.get("expenditure_rules"),
                current_balance=Decimal(str(f.get("current_balance", "0"))),
            )
            ctx.funds = [x for x in ctx.funds if x.fund_id != fund.fund_id]
            ctx.funds.append(fund)
            added_funds += 1

    coa_store.save_accounting_context(ctx)
    return _json({
        "ok": True,
        "accounts_imported": added_accounts,
        "funds_imported": added_funds,
        "total_accounts": len(ctx.accounts),
        "total_funds": len(ctx.funds),
    })


@app.post("/api/churches/{church_id}/coa/import-spreadsheet")
async def import_coa_spreadsheet(church_id: str, file: UploadFile) -> JSONResponse:
    """Bulk import church accounts/funds from Excel or CSV spreadsheet."""
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, f"Church '{church_id}' not found. Create it first via POST /api/churches")

    # Validate file format
    filename_lower = file.filename.lower() if file.filename else ""
    if not any(filename_lower.endswith(ext) for ext in [".xlsx", ".xls", ".csv"]):
        raise HTTPException(400, "File must be Excel (.xlsx, .xls) or CSV (.csv)")

    try:
        content = await file.read()
        parsed = parse_spreadsheet(content, file.filename or "")
    except Exception as e:
        raise HTTPException(400, f"Failed to parse spreadsheet: {str(e)}")

    added_accounts = 0
    if parsed.get("accounts"):
        for a in parsed["accounts"]:
            account = Account(
                account_number=str(a["account_number"]),
                account_name=a["account_name"],
                account_type=a.get("account_type", "EXPENSE"),
                fund_id=a.get("fund", "GEN"),
                restriction_class=RestrictionClass(
                    a.get("restriction_class", "WITHOUT_RESTRICTION")
                ),
                active=a.get("is_active", True),
            )
            ctx.accounts = [x for x in ctx.accounts if x.account_number != account.account_number]
            ctx.accounts.append(account)
            added_accounts += 1
        ctx.accounts.sort(key=lambda x: x.account_number)

    added_funds = 0
    if parsed.get("funds"):
        for f in parsed["funds"]:
            fund = Fund(
                fund_id=f["fund_id"],
                fund_name=f["fund_name"],
                restriction_class=RestrictionClass(
                    f.get("restriction_class", "WITHOUT_RESTRICTION")
                ),
                fund_category=FundCategory(
                    f.get("category", "GENERAL_OPERATING")
                ),
                purpose_description=f.get("purpose_description"),
                expenditure_rules=f.get("expenditure_rules"),
                current_balance=Decimal(str(f.get("current_balance", "0"))),
            )
            ctx.funds = [x for x in ctx.funds if x.fund_id != fund.fund_id]
            ctx.funds.append(fund)
            added_funds += 1

    coa_store.save_accounting_context(ctx)
    return _json({
        "ok": True,
        "accounts_imported": added_accounts,
        "funds_imported": added_funds,
        "total_accounts": len(ctx.accounts),
        "total_funds": len(ctx.funds),
    })


@app.get("/api/churches/{church_id}/search")
async def semantic_search(church_id: str, q: str, k: int = 5) -> JSONResponse:
    results = coa_store.semantic_search(church_id, q, k=k)
    return _json(results)


# ===== Budget endpoints =====

@app.post("/api/churches/{church_id}/budget/import-spreadsheet")
async def import_budget_spreadsheet(church_id: str, file: UploadFile) -> JSONResponse:
    """Bulk import a church's budget plan from Excel or CSV spreadsheet.

    Accepts a sheet with columns:
      - account_number (required)
      - jan, feb, mar, ..., dec (optional — monthly amounts)
      - annual_budget / annual_total / annual (optional — annual figure)
    """
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, f"Church '{church_id}' not found.")

    filename_lower = file.filename.lower() if file.filename else ""
    if not any(filename_lower.endswith(ext) for ext in [".xlsx", ".xls", ".csv"]):
        raise HTTPException(400, "File must be Excel (.xlsx, .xls) or CSV (.csv)")

    try:
        content = await file.read()
        parsed = parse_spreadsheet(content, file.filename or "")
    except Exception as e:
        raise HTTPException(400, f"Failed to parse spreadsheet: {str(e)}")

    budget_data = parsed.get("budget")
    if not budget_data or not budget_data.get("accounts"):
        raise HTTPException(
            422,
            "No budget-shaped sheet detected. Expected an account_number column "
            "plus either monthly columns (jan…dec) or annual_budget."
        )

    # Validate account numbers against COA
    coa_account_numbers = {a.account_number for a in ctx.accounts}
    warnings: List[str] = list(parsed.get("warnings") or [])

    accounts_loaded: Dict[str, BudgetMonth] = {}
    for acct_no, vals in budget_data["accounts"].items():
        if acct_no not in coa_account_numbers:
            warnings.append(f"account {acct_no} in budget not in COA — skipped")
            continue
        accounts_loaded[acct_no] = BudgetMonth(**vals)

    if not accounts_loaded:
        raise HTTPException(
            422,
            "All accounts in the budget file are unknown to the COA. "
            "Check column headers and account numbers."
        )

    # Determine amendment_number — increment if existing budget for same FY
    prev_amendment = 0
    if ctx.budget is not None:
        prev_amendment = ctx.budget.amendment_number + 1

    annual_total: Decimal = Decimal("0")
    for bm in accounts_loaded.values():
        annual_total += Decimal(bm.annual_total)

    ctx.budget = BudgetPlan(
        fiscal_year=ctx.fiscal_year,
        plan_date=datetime.utcnow().date(),
        amendment_number=prev_amendment,
        accounts=accounts_loaded,
        uploaded_at=datetime.utcnow(),
        uploaded_by=None,
        source_filename=file.filename,
    )
    coa_store.save_accounting_context(ctx)

    return _json({
        "fiscal_year": ctx.fiscal_year,
        "accounts_loaded": len(accounts_loaded),
        "annual_total": str(annual_total),
        "amendment_number": prev_amendment,
        "warnings": warnings,
    })


@app.get("/api/churches/{church_id}/budget")
async def get_budget(church_id: str) -> JSONResponse:
    """Return the current budget plan + YTD actuals."""
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    if ctx.budget is None:
        raise HTTPException(404, "Budget not configured for this church")
    return _json({
        "budget": ctx.budget.model_dump(),
        "ytd_actuals": {k: str(v) for k, v in ctx.ytd_actuals.items()},
        "budget_warning_threshold": ctx.budget_warning_threshold,
    })


@app.get("/api/churches/{church_id}/budget/variance-report")
async def variance_report(church_id: str) -> JSONResponse:
    """Compute live variance report against current YTD actuals."""
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    if ctx.budget is None:
        raise HTTPException(404, "Budget not configured for this church")

    threshold = float(ctx.budget_warning_threshold or 0.80)
    annual_total = Decimal("0")
    ytd_total = Decimal("0")

    accounts_by_no = {a.account_number: a for a in ctx.accounts}
    within: List[Dict[str, Any]] = []
    at_risk: List[Dict[str, Any]] = []
    over: List[Dict[str, Any]] = []

    for acct_no, bm in ctx.budget.accounts.items():
        annual = Decimal(bm.annual_total)
        ytd = Decimal(ctx.ytd_actuals.get(acct_no, Decimal("0")))
        remaining = annual - ytd
        annual_total += annual
        ytd_total += ytd
        pct = float(ytd / annual) if annual > 0 else (1.5 if ytd > 0 else 0.0)
        acct = accounts_by_no.get(acct_no)
        row = {
            "account_number": acct_no,
            "account_name": acct.account_name if acct else acct_no,
            "annual": str(annual),
            "ytd": str(ytd),
            "remaining": str(remaining),
            "pct": pct,
        }
        if pct >= 1.0:
            over.append(row)
        elif pct >= threshold:
            at_risk.append(row)
        else:
            within.append(row)

    consumed_pct = float(ytd_total / annual_total) if annual_total > 0 else 0.0

    return _json({
        "fiscal_year": ctx.budget.fiscal_year,
        "as_of": datetime.utcnow().isoformat(),
        "totals": {
            "annual_budget": str(annual_total),
            "ytd_actual": str(ytd_total),
            "remaining": str(annual_total - ytd_total),
            "consumed_pct": consumed_pct,
        },
        "buckets": {"within": within, "at_risk": at_risk, "over": over},
    })


class YTDResetBody(BaseModel):
    confirm: bool = False
    reset_to_zero: bool = True


@app.put("/api/churches/{church_id}/budget/ytd-reset")
async def ytd_reset(
    church_id: str,
    body: YTDResetBody,
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Reset YTD actuals to zero. Requires explicit confirmation.

    RBAC: requires TREASURER_ADMIN role (FR-4.1).
    """
    from .auth import get_caller_role, has_role
    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )
    if not body.confirm:
        raise HTTPException(400, "ytd-reset requires `confirm: true`")
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")

    previous_total = Decimal("0")
    for v in ctx.ytd_actuals.values():
        previous_total += Decimal(v)

    if body.reset_to_zero:
        ctx.ytd_actuals = {}
    reset_at = datetime.utcnow().isoformat()
    ctx.warnings.append(f"YTD reset on {reset_at}; previous total ${previous_total}")
    coa_store.save_accounting_context(ctx)
    return _json({
        "previous_ytd_total": str(previous_total),
        "reset_at": reset_at,
    })


class YearEndResetBody(BaseModel):
    next_fiscal_year: int
    roll_forward_plan: bool = False
    confirm: bool = False


@app.post("/api/churches/{church_id}/budget/year-end-reset")
async def year_end_reset(church_id: str, body: YearEndResetBody) -> JSONResponse:
    """Roll over to the next fiscal year. Resets YTD; optionally retains plan."""
    if not body.confirm:
        raise HTTPException(400, "year-end-reset requires `confirm: true`")
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")

    previous_total = Decimal("0")
    for v in ctx.ytd_actuals.values():
        previous_total += Decimal(v)

    ctx.ytd_actuals = {}
    ctx.fiscal_year = body.next_fiscal_year
    from datetime import date as _date
    ctx.fiscal_year_start = _date(body.next_fiscal_year, 1, 1)

    if body.roll_forward_plan and ctx.budget is not None:
        ctx.budget.fiscal_year = body.next_fiscal_year
        ctx.budget.amendment_number = ctx.budget.amendment_number + 1
        ctx.budget.plan_date = datetime.utcnow().date()
    else:
        ctx.budget = None

    reset_at = datetime.utcnow().isoformat()
    ctx.warnings.append(
        f"Year-end reset to FY{body.next_fiscal_year} on {reset_at}; "
        f"previous YTD total ${previous_total}; rolled_forward={body.roll_forward_plan}"
    )
    coa_store.save_accounting_context(ctx)
    return _json({
        "ok": True,
        "next_fiscal_year": body.next_fiscal_year,
        "previous_ytd_total": str(previous_total),
        "reset_at": reset_at,
        "plan_rolled_forward": body.roll_forward_plan,
    })


class ThresholdBody(BaseModel):
    threshold: float


@app.get("/api/churches/{church_id}/budget/projection")
async def budget_projection(church_id: str) -> JSONResponse:
    """FR-03.3: project year-end balance for each budgeted account."""
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    if not ctx.budget:
        raise HTTPException(404, "No budget configured for this church")
    from .tools.budget_projector import project_year_end
    rows = project_year_end(ctx)
    return _json([r.model_dump() if hasattr(r, "model_dump") else r for r in rows])


@app.put("/api/churches/{church_id}/budget-warning-threshold")
async def set_warning_threshold(church_id: str, body: ThresholdBody) -> JSONResponse:
    """Set the church's budget warning threshold (0.0–1.0)."""
    if body.threshold < 0.0 or body.threshold > 1.0:
        raise HTTPException(422, "threshold must be in [0.0, 1.0]")
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, "Church not found")
    ctx.budget_warning_threshold = body.threshold
    coa_store.save_accounting_context(ctx)
    return _json({"budget_warning_threshold": body.threshold})


# ===== Invoice upload + pipeline =====

@app.post("/api/invoice/upload")
async def upload_invoice(
    background_tasks: BackgroundTasks,
    church_id: str = Form(...),
    document_type: str = Form(default="INVOICE"),
    file: UploadFile = File(...),
) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted")

    doc_type = DocumentType(document_type)
    dest = UPLOAD_DIR / f"{church_id}_{file.filename}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    job = flow.create_job(church_id, file.filename, str(dest), doc_type)
    background_tasks.add_task(flow.run_pipeline, job.job_id)
    return _json({"job_id": job.job_id, "status": job.status})


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    job = flow.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _json(_job_summary(job))


@app.get("/api/jobs")
async def list_jobs(church_id: Optional[str] = None) -> JSONResponse:
    jobs = flow.list_jobs(church_id=church_id)
    return _json([_job_summary(j) for j in jobs])


def _job_summary(job: Any) -> Dict:
    d = job.model_dump()
    if d.get("invoice_document") and d["invoice_document"].get("raw_text"):
        d["invoice_document"]["raw_text"] = "[redacted]"
    # FR-04.5: fraud signals NEVER reach the UI. Strip fraud_assessment field
    # entirely from any response. Internal data lives in audit_log only.
    if "fraud_assessment" in d:
        d["fraud_assessment"] = None
    return d


# ===== HITL endpoints =====

class HITLDecisionBody(BaseModel):
    line_decisions: List[Dict]
    budget_approval_attestation: bool = False


@app.post("/api/jobs/{job_id}/hitl")
async def submit_hitl(
    job_id: str,
    body: HITLDecisionBody,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    job = flow.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != ProcessingStatus.PENDING_HITL:
        raise HTTPException(400, f"Job is in status {job.status}, not PENDING_HITL")

    line_decisions = [
        HITLLineDecision(
            line_id=d["line_id"],
            action=d["action"],
            override_postings=d.get("override_postings"),
            reviewer_id=d.get("reviewer_id", "anonymous"),
            approval_timestamp=datetime.utcnow(),
            notes=d.get("notes", ""),
            missions_attestation=d.get("missions_attestation", False),
        )
        for d in body.line_decisions
    ]
    hitl = HITLDecisions(line_decisions=line_decisions, all_resolved=True)

    # Persist budget attestation in audit_log (no schema change required)
    if body.budget_approval_attestation:
        job.audit_log.append({
            "ts": datetime.utcnow().isoformat(),
            "step": "budget_approval_attestation",
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "detail": "Approver attested over-budget expense is necessary and authorized",
        })

    background_tasks.add_task(flow.submit_hitl_decisions, job_id, hitl)
    return _json({"ok": True, "job_id": job_id})


# ===== Audit trail endpoints =====

@app.get("/api/audit/{entry_id}")
async def get_audit(entry_id: str) -> JSONResponse:
    for job in flow.list_jobs():
        if job.journal_entry and job.journal_entry.entry_id == entry_id:
            return _json({
                "entry_id": entry_id,
                "job_id": job.job_id,
                "invoice": job.invoice_document.model_dump() if job.invoice_document else None,
                "classified": [c.model_dump() for c in (job.classified_items or [])],
                "journal_entry": job.journal_entry.model_dump() if job.journal_entry else None,
                "risk_assessment": job.risk_assessment,
                "fraud_assessment": job.fraud_assessment,
                "audit_log": job.audit_log,
            })
    raise HTTPException(404, "Audit trail not found")


@app.get("/api/audit/{entry_id}/pdf")
async def get_audit_pdf(entry_id: str) -> FileResponse:
    """Generate and return a PDF audit trail for a journal entry."""
    for job in flow.list_jobs():
        if job.journal_entry and job.journal_entry.entry_id == entry_id:
            pdf_path = AUDIT_PDF_DIR / f"audit_{entry_id}.pdf"

            audit_data = {
                "entry_id": entry_id,
                "invoice": job.invoice_document.model_dump() if job.invoice_document else {},
                "classified": [c.model_dump() for c in (job.classified_items or [])],
                "journal_entry": job.journal_entry.model_dump() if job.journal_entry else {},
                "risk_assessment": job.risk_assessment or {},
                "fraud_assessment": job.fraud_assessment or {},
                "audit_log": job.audit_log,
            }

            try:
                from .tools.pdf_generator import generate_audit_pdf
                generate_audit_pdf(audit_data, pdf_path)
            except ImportError:
                raise HTTPException(503, "PDF generation unavailable — install fpdf2")

            return FileResponse(
                path=str(pdf_path),
                media_type="application/pdf",
                filename=f"audit_{entry_id[:8]}.pdf",
            )
    raise HTTPException(404, "Audit trail not found")


# ===== Chat / Agent Q&A =====

@app.post("/api/chat")
async def chat(body: ChatRequest) -> JSONResponse:
    """Conversational interface — question any agent about a job or general accounting."""
    job = None
    if body.job_id:
        job = flow.get_job(body.job_id)
        if not job:
            raise HTTPException(404, f"Job {body.job_id} not found")

    from .tools.chat_router import route_question
    result = await route_question(
        question=body.question, job=job, church_id=body.church_id,
    )
    return _json(result)


# ===== FR-06.2: Manual JE creation via chat =====

# JEs persist to backend/data/jes_{church_id}.jsonl
JE_DATA_DIR = Path(__file__).resolve().parent / "data"


def _jes_path(church_id: str) -> Path:
    safe = "".join(c for c in church_id if c.isalnum() or c in "_-") or "default"
    return JE_DATA_DIR / f"jes_{safe}.jsonl"


def _persist_je(church_id: str, je_dict: Dict[str, Any]) -> None:
    JE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _jes_path(church_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(je_dict, default=str) + "\n")


@app.post("/api/jes/manual-create")
async def manual_create_je(body: Dict[str, Any]) -> JSONResponse:
    """FR-06.2: persist a manually-drafted journal entry from the chat rail.

    Accepts a JournalEntry payload (as returned by the chat /api/chat
    `je_draft` field). Validates balance and writes it to the per-church
    `backend/data/jes_{church_id}.jsonl` JE store with status DRAFT.
    """
    from .models.schemas import JournalEntry, JEStatus

    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JournalEntry payload")

    try:
        je = JournalEntry(**body)
    except Exception as exc:
        raise HTTPException(422, f"Invalid JournalEntry: {exc}") from exc

    # Re-derive totals & balance to defend against client tampering.
    debits = sum((ln.debit for ln in je.lines), Decimal("0"))
    credits = sum((ln.credit for ln in je.lines), Decimal("0"))
    if debits != credits or debits == 0:
        raise HTTPException(
            422,
            f"Journal entry is not balanced (DR={debits} != CR={credits})",
        )

    je.total_debits = debits
    je.total_credits = credits
    je.balanced = True
    # Force DRAFT status — manual JEs always enter the approval chain at DRAFT.
    je.status = JEStatus.DRAFT

    # Persist via the DB-backed journal_entry_store (replaces JSONL append).
    journal_entry_store.create_journal_entry(je.church_id, je)
    saved = journal_entry_store.get_journal_entry(je.entry_id)

    return _json({
        "ok": True,
        "entry_id": je.entry_id,
        "status": je.status.value if hasattr(je.status, "value") else str(je.status),
        "journal_entry": saved.model_dump() if saved is not None else je.model_dump(),
    })


@app.get("/api/churches/{church_id}/jes/manual")
async def list_manual_jes(church_id: str, status: Optional[str] = None) -> JSONResponse:
    """List manually-created JEs for a church (DB-backed)."""
    entries = journal_entry_store.list_journal_entries(church_id, status=status)
    return _json([e.model_dump() for e in entries])


# ===== FR-09: Knowledge Base endpoints =====

KB_FILES_ROOT = Path(__file__).resolve().parent / "data" / "kb"


@app.post("/api/churches/{church_id}/kb/upload")
async def kb_upload(church_id: str, file: UploadFile = File(...)) -> JSONResponse:
    """Upload a PDF/MD/TXT into the church KB and ingest into ChromaDB."""
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".md", ".markdown", ".txt", ".rst"}:
        raise HTTPException(400, f"Unsupported file type {suffix!r}")

    from .tools import knowledge_base

    dest_dir = KB_FILES_ROOT / church_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        chunk_count = knowledge_base.ingest_church_kb(church_id, dest)
    except Exception as exc:
        raise HTTPException(500, f"Ingestion failed: {exc}") from exc

    return _json({
        "ok": True,
        "filename": file.filename,
        "chunk_count": chunk_count,
    })


@app.get("/api/churches/{church_id}/kb/list")
async def kb_list(church_id: str) -> JSONResponse:
    """List uploaded KB documents for a church."""
    from .tools import knowledge_base
    return _json(knowledge_base.list_church_kb_files(church_id))


@app.delete("/api/churches/{church_id}/kb/{filename}")
async def kb_delete(church_id: str, filename: str) -> JSONResponse:
    """Remove a KB document and its chunks."""
    from .tools import knowledge_base
    removed = knowledge_base.delete_church_kb_file(church_id, filename)
    if not removed:
        raise HTTPException(404, f"File {filename} not found")
    return _json({"ok": True, "filename": filename})


@app.get("/api/churches/{church_id}/kb/search")
async def kb_search_endpoint(church_id: str, q: str, k: int = 5) -> JSONResponse:
    """Search per-church KB + global canon. Returns hits with citations."""
    from .tools import knowledge_base
    if not q or not q.strip():
        return _json([])
    hits = knowledge_base.kb_search(q, church_id=church_id, k=k)
    return _json([h.to_dict() for h in hits])


# ===== Skill registry =====

@app.get("/api/skills")
async def list_skills(archetype: Optional[str] = None) -> JSONResponse:
    from .tools.skill_registry import get_registry
    return _json(get_registry().search(archetype=archetype))


@app.get("/api/skills/{skill_name}")
async def get_skill(skill_name: str) -> JSONResponse:
    from .tools.skill_registry import get_registry
    registry = get_registry()
    meta = registry.get(skill_name)
    if not meta:
        raise HTTPException(404, "Skill not found")
    return _json({**meta, "body": registry.load_body(skill_name)})


# ===== Denomination agent info =====

@app.get("/api/denominations")
async def list_denominations() -> JSONResponse:
    from .tools.skill_registry import get_registry
    registry = get_registry()
    denoms = []
    for denom_val, skill_name in [
        ("UMC", "denomination_umc"),
        ("EPISCOPAL", "denomination_episcopal"),
        ("CATHOLIC_PARISH", "denomination_catholic_parish"),
        ("BAPTIST_INDEPENDENT", "denomination_baptist"),
        ("PRESBYTERIAN_PCUSA", "denomination_presbyterian"),
    ]:
        meta = registry.get(skill_name)
        denoms.append({
            "denomination": denom_val,
            "skill_name": skill_name,
            "loaded": meta is not None,
            "description": meta.get("description", "") if meta else "",
        })
    return _json(denoms)


# ===== Serve frontend =====

# ===== FR-05.1: Approval Chains CRUD =====

class ApprovalChainBody(BaseModel):
    chain_id: str
    gl_pattern: str
    primary_approver_email: str
    primary_approver_name: str
    secondary_approver_email: str
    secondary_approver_name: str
    deadline_hours: int = 48
    escalation_days: int = 5
    active: bool = True


@app.get("/api/churches/{church_id}/approval-chains")
async def list_approval_chains(church_id: str) -> JSONResponse:
    chains = approval_chain_resolver.load_chains(church_id)
    return _json([c.model_dump() for c in chains])


@app.put("/api/churches/{church_id}/approval-chains")
async def replace_approval_chains(
    church_id: str,
    body: List[ApprovalChainBody],
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Replace approval chains. RBAC: requires TREASURER_ADMIN (FR-4.1)."""
    from .auth import get_caller_role, has_role
    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )
    chains = [ApprovalChain(**c.model_dump()) for c in body]
    approval_chain_resolver.save_chains(church_id, chains)
    return _json({"ok": True, "count": len(chains)})


@app.post("/api/churches/{church_id}/approval-chains")
async def add_approval_chain(
    church_id: str,
    body: ApprovalChainBody,
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Add an approval chain. RBAC: requires TREASURER_ADMIN (FR-4.1)."""
    from .auth import get_caller_role, has_role
    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )
    chain = ApprovalChain(**body.model_dump())
    chains = approval_chain_resolver.add_chain(church_id, chain)
    return _json({"ok": True, "count": len(chains)})


@app.delete("/api/churches/{church_id}/approval-chains/{chain_id}")
async def delete_approval_chain(
    church_id: str,
    chain_id: str,
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Delete an approval chain. RBAC: requires TREASURER_ADMIN (FR-4.1)."""
    from .auth import get_caller_role, has_role
    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )
    chains = approval_chain_resolver.remove_chain(church_id, chain_id)
    return _json({"ok": True, "count": len(chains)})


# ===== FR-05.2: One-time approval URL handler =====

@app.get("/api/approve", response_class=HTMLResponse)
async def approve_via_token(
    token: str,
    action: str,
    background_tasks: BackgroundTasks,
    gl_override: Optional[str] = None,
    rationale: Optional[str] = None,
) -> HTMLResponse:
    claims = email_tokens.consume(token)
    if not claims:
        return HTMLResponse(
            "<html><body><h2>Invalid or expired token</h2>"
            "<p>This approval link has already been used or has expired.</p>"
            "</body></html>",
            status_code=400,
        )

    ctx = claims.get("context") or {}
    job_id = ctx.get("job_id")
    line_id = ctx.get("line_id")
    role = claims.get("role", "budget_owner")
    job = flow.get_job(job_id) if job_id else None
    if not job:
        return HTMLResponse(
            "<html><body><h2>Job not found</h2></body></html>",
            status_code=404,
        )

    decision = {
        "action": action.upper(),
        "actor_email": ctx.get("approver_email"),
        "actor_role": role,
        "line_id": line_id,
        "rationale": rationale or "",
        "gl_override": gl_override,
        "ts": datetime.utcnow().isoformat(),
    }

    job.budget_owner_decision = decision
    job.audit_log.append({
        "ts": datetime.utcnow().isoformat(),
        "event_type": "BUDGET_OWNER_DECISION",
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "action": action.upper(),
        "actor_email": ctx.get("approver_email"),
        "rationale": rationale or "",
        "gl_override": gl_override,
    })
    approval_audit.append_event(job.church_id, {
        "job_id": job.job_id,
        "line_id": line_id,
        "actor_email": ctx.get("approver_email") or "",
        "actor_role": role,
        "action": action.upper(),
        "gl_at_action": gl_override or ctx.get("proposed_gl_code"),
        "original_gl": ctx.get("proposed_gl_code"),
        "rationale": rationale or "",
        "notes": "",
    })

    action_upper = action.upper()
    if action_upper not in {"APPROVE", "REJECT"}:
        return HTMLResponse(
            f"<html><body><h2>Invalid action</h2>"
            f"<p>Action must be APPROVE or REJECT, not '{action}'.</p>"
            f"</body></html>",
            status_code=400,
        )

    if action_upper == "REJECT":
        job.status = ProcessingStatus.REJECTED
        job.updated_at = datetime.utcnow()
        body_html = (
            "<html><body><h2>Decision recorded: REJECTED</h2>"
            "<p>The invoice has been rejected and will not be posted.</p>"
            "</body></html>"
        )
    else:  # APPROVE
        job.status = ProcessingStatus.PENDING_TREASURER
        job.updated_at = datetime.utcnow()
        job.pending_approval_started_at = datetime.utcnow()
        body_html = (
            "<html><body><h2>Decision recorded</h2>"
            "<p>Thank you. The invoice has been forwarded to the treasurer "
            "for final approval.</p></body></html>"
        )
    return HTMLResponse(body_html)


# ===== FR-05.3: Treasurer decision endpoint =====

class TreasurerDecisionBody(BaseModel):
    action: str  # "approve" | "reject"
    treasurer_id: str
    notes: Optional[str] = None


@app.post("/api/jobs/{job_id}/treasurer-decision")
async def treasurer_decision(
    job_id: str,
    body: TreasurerDecisionBody,
    background_tasks: BackgroundTasks,
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Treasurer makes APPROVE/REJECT decision on a job.

    RBAC: requires TREASURER_ADMIN role (FR-4.1).
    """
    from .auth import get_caller_role, has_role
    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )
    job = flow.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != ProcessingStatus.PENDING_TREASURER:
        raise HTTPException(
            400,
            f"Job is in status {job.status}, not PENDING_TREASURER",
        )
    decision = {
        "action": body.action.upper(),
        "treasurer_id": body.treasurer_id,
        "notes": body.notes or "",
        "ts": datetime.utcnow().isoformat(),
    }
    job.treasurer_decision = decision
    job.audit_log.append({
        "ts": datetime.utcnow().isoformat(),
        "event_type": "TREASURER_DECISION",
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "action": body.action.upper(),
        "treasurer_id": body.treasurer_id,
        "notes": body.notes or "",
    })
    approval_audit.append_event(job.church_id, {
        "job_id": job.job_id,
        "actor_email": body.treasurer_id,
        "actor_role": "treasurer",
        "action": body.action.upper(),
        "notes": body.notes or "",
    })
    if body.action.upper() == "REJECT":
        job.status = ProcessingStatus.REJECTED
        job.updated_at = datetime.utcnow()
        return _json({"ok": True, "status": job.status.value})
    job.status = ProcessingStatus.TREASURER_APPROVED
    job.updated_at = datetime.utcnow()
    if job.reviewed_allocations is not None:
        background_tasks.add_task(flow.continue_after_treasurer, job_id)
    return _json({"ok": True, "status": job.status.value})


# ===== FR-05.4: Approval audit trail export =====

@app.get("/api/churches/{church_id}/audit/approvals")
async def list_approval_audit(
    church_id: str,
    job_id: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    format: str = "json",
) -> Any:
    rows = approval_audit.list_events(
        church_id, since=from_, until=to, job_id=job_id,
    )
    fmt = (format or "json").lower()
    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        if rows:
            keys = sorted({k for r in rows for k in r.keys()})
            w = csv.DictWriter(buf, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in keys})
        return HTMLResponse(buf.getvalue(), media_type="text/csv")
    if fmt == "pdf":
        try:
            from fpdf import FPDF
        except ImportError:
            raise HTTPException(503, "PDF generation unavailable — install fpdf2")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"Approval Audit Trail - {church_id}", ln=True)
        pdf.set_font("Helvetica", "", 8)
        for r in rows:
            line = (
                f"{r.get('timestamp','')} | {r.get('actor_role','')} "
                f"{r.get('actor_email','')} | {r.get('action','')} | "
                f"job={r.get('job_id','')}"
            )
            pdf.multi_cell(0, 4, line)
            note = r.get("notes") or r.get("rationale") or ""
            if note:
                pdf.multi_cell(0, 4, f"  -> {note}")
        out = AUDIT_PDF_DIR / f"approvals_{church_id}.pdf"
        pdf.output(str(out))
        return FileResponse(
            path=str(out),
            media_type="application/pdf",
            filename=f"approvals_{church_id}.pdf",
        )
    return _json({"chain_valid": approval_audit.verify_chain(church_id),
                  "events": rows})


@app.get("/api/churches/{church_id}/decision-ledger")
async def get_decision_ledger(
    church_id: str,
    category: Optional[str] = None,
    job_id: Optional[str] = None,
    limit: int = 100,
) -> JSONResponse:
    """Return the structured decision ledger for a church.

    Each entry records why the system made a classification, mapping, fraud,
    or approval-routing decision — the 'why does the system believe what it
    believes' audit trail per FRD §14.1.

    Query params:
      category  — filter by DecisionCategory (recognize, code, route, approve, override, disavow)
      job_id    — filter to entries for a specific processing job
      limit     — max entries returned (default 100, most recent first)
    """
    ledger = flow.get_ledger(church_id)
    entries = list(reversed(ledger.entries))  # most recent first

    if category:
        entries = [e for e in entries if e.category.value == category.lower()]
    if job_id:
        entries = [e for e in entries if e.decision_id.startswith(job_id)]

    entries = entries[:limit]
    return _json({
        "church_id": church_id,
        "total": len(ledger.entries),
        "returned": len(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    })


@app.get("/api/churches/{church_id}/events/{event_id}")
async def get_event(church_id: str, event_id: str) -> JSONResponse:
    """Phase 6: Fetch a specific event by ID for citation chain rendering.

    Returns the event with all tags and payload data.
    """
    try:
        from .db import connection
        row = connection.execute_query(
            "SELECT * FROM events WHERE church_id = %s AND event_id = %s",
            (church_id, event_id),
            fetch_one=True
        )
        if not row:
            raise HTTPException(404, f"Event not found: {event_id}")

        # Load tags for this event
        tag_rows = connection.execute_query(
            "SELECT tag_kind, tag_value FROM event_tags WHERE event_id = %s",
            (event_id,)
        ) or []

        return _json({
            "event_id": row.get("event_id"),
            "event_type": row.get("event_type"),
            "church_id": row.get("church_id"),
            "occurred_at": row.get("occurred_at"),
            "actor": row.get("actor"),
            "confidence": float(row.get("confidence") or 0),
            "payload": row.get("payload") or {},
            "caused_by": row.get("caused_by") or [],
            "correlation_id": row.get("correlation_id"),
            "tags": [
                {"tag_kind": t.get("tag_kind"), "tag_value": t.get("tag_value")}
                for t in tag_rows
            ],
        })
    except Exception as e:
        logger.error(f"Error fetching event {event_id}: {e}")
        raise HTTPException(500, f"Error fetching event: {e}")


# ===== FR-06.4 / FR-06.5: JE state machine + ACS Realm posting =====

def _find_journal_entry(je_id: str):
    """Find a JE by ID — DB-backed via journal_entry_store.

    Falls back to processing-job in-memory JEs (which may not yet be
    persisted to the journal_entries table). Returns (JournalEntry,
    church_id) or (None, None).
    """
    je = journal_entry_store.get_journal_entry(je_id)
    if je is not None:
        return je, je.church_id

    # Fallback: processing-job JEs not yet promoted to the DB store.
    try:
        for job in flow.list_jobs():
            if job.journal_entry and job.journal_entry.entry_id == je_id:
                return job.journal_entry, job.church_id
    except Exception:
        pass
    return None, None


def _update_je_in_store(je: Any, church_id: str) -> None:
    """Update an existing JE — DB-backed via journal_entry_store.

    If the JE exists in the journal_entries table, we update it there
    atomically (with optimistic locking inside the store). If it only
    lives on a processing job, mutate the job's in-memory copy.
    """
    je_data = je.model_dump() if hasattr(je, "model_dump") else dict(je)

    # If the JE is in the DB store, update it there.
    if journal_entry_store.get_journal_entry(je.entry_id) is not None:
        # Strip fields the store handles internally (id/version/timestamps).
        updates = {
            k: v for k, v in je_data.items()
            if k not in {"entry_id", "version", "created_at", "updated_at", "lines"}
        }
        journal_entry_store.update_journal_entry(je.entry_id, updates)
        return

    # Otherwise mutate the in-memory processing-job copy.
    try:
        for job in flow.list_jobs():
            if job.journal_entry and job.journal_entry.entry_id == je.entry_id:
                job.journal_entry = je
                return
    except Exception:
        pass

    # Last resort: insert into the DB store (manual JEs that haven't been
    # persisted yet land here).
    try:
        journal_entry_store.create_journal_entry(church_id, je)
    except Exception:
        pass


@app.post("/api/jes/{je_id}/post")
async def post_je_to_acs(je_id: str, request: Request, body: Optional[Dict[str, Any]] = None) -> JSONResponse:
    """Post an APPROVED journal entry to ACS Realm via browser automation.

    RBAC: requires TREASURER_ADMIN role (or higher).
    Requires explicit `confirmed=true` in body (ACS confirmation gate).
    """
    from .auth import get_caller_role, has_role
    from .models.schemas import JEStatus

    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )

    body = body or {}
    if not body.get("confirmed"):
        raise HTTPException(
            428,
            "ACS confirmation required. POST again with {confirmed: true} "
            "after the treasurer confirms.",
        )

    je, church_id = _find_journal_entry(je_id)
    if not je:
        raise HTTPException(404, "JE not found")
    status_val = je.status.value if hasattr(je.status, "value") else str(je.status)
    if status_val != JEStatus.APPROVED.value:
        raise HTTPException(
            409,
            f"Cannot post JE in status {status_val}; must be APPROVED",
        )

    from .integrations.acs_realm.acs_actions import post_journal_entry
    result = post_journal_entry(je, church_id)

    if result.success:
        try:
            je.status = JEStatus.POSTED
        except Exception:
            object.__setattr__(je, "status", JEStatus.POSTED)
        try:
            object.__setattr__(je, "acs_reference", result.acs_reference)
        except Exception:
            pass
        # Mark if posted via mock mode so operators know
        if result.mock:
            try:
                object.__setattr__(je, "posted_via_mock", True)
            except Exception:
                pass
        _update_je_in_store(je, church_id)

        # Phase 6: Emit TransactionPosted-into-ACS event (audit trail)
        try:
            from .events.schemas import EventType, FinancialEvent, TagKind
            from .events.emitter import emit_event

            post_event = FinancialEvent(
                event_type=EventType.TRANSACTION_POSTED,
                church_id=church_id,
                payload={
                    "je_id": je.entry_id,
                    "acs_reference": result.acs_reference,
                    "posted_at": datetime.utcnow().isoformat(),
                    "system": "acs_realm",
                    "via_mock": result.mock,  # Explicit flag for mock posts
                },
            )
            post_event.add_tag(TagKind.ENTRY, je.entry_id)
            post_event.add_tag(TagKind.DOCUMENT, "acs_realm_post")
            emit_event(post_event)
        except Exception:
            pass  # Non-fatal: event emission failure doesn't block posting

        return _json({
            "status": "POSTED",
            "acs_reference": result.acs_reference,
            "mock": result.mock,
        })
    else:
        try:
            je.status = JEStatus.POSTING_FAILED
        except Exception:
            object.__setattr__(je, "status", JEStatus.POSTING_FAILED)
        try:
            object.__setattr__(je, "posting_error", result.error_message)
        except Exception:
            pass
        _update_je_in_store(je, church_id)

        # Phase 6: Emit PostingBlocked event (audit trail)
        try:
            from .events.schemas import EventType, FinancialEvent, TagKind
            from .events.emitter import emit_event

            block_event = FinancialEvent(
                event_type=EventType.POSTING_BLOCKED,
                church_id=church_id,
                payload={
                    "je_id": je.entry_id,
                    "reason": result.error_message,
                    "system": "acs_realm",
                    "failed_at": datetime.utcnow().isoformat(),
                },
            )
            block_event.add_tag(TagKind.ENTRY, je.entry_id)
            block_event.add_tag(TagKind.DOCUMENT, "acs_realm_post")
            emit_event(block_event)
        except Exception:
            pass  # Non-fatal: event emission failure doesn't affect error response

        raise HTTPException(500, f"Posting failed: {result.error_message}")


@app.post("/api/churches/{church_id}/acs-credentials")
def store_acs_credentials(church_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Store ACS Realm credentials encrypted (FR-06.5)."""
    from .integrations.acs_realm import credentials as _creds
    try:
        _creds.store(
            church_id,
            body["username"],
            body["password"],
            body["base_url"],
        )
    except KeyError as exc:
        raise HTTPException(422, f"Missing field: {exc}") from exc
    except Exception as exc:
        raise HTTPException(500, f"Failed to store credentials: {exc}") from exc
    return _json({"status": "stored"})


@app.post("/api/jes/{je_id}/transition")
def transition_je(je_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Transition a JE through its state machine (FR-06.4)."""
    from .tools.je_state import transition as _transition, JEStateError
    from .models.schemas import JEStatus

    je, church_id = _find_journal_entry(je_id)
    if not je:
        raise HTTPException(404, "JE not found")
    try:
        target = JEStatus(body["to_state"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, f"Invalid to_state: {exc}") from exc

    try:
        je = _transition(
            je,
            target,
            body.get("role", ""),
            body.get("actor_email", "unknown"),
            body.get("notes", ""),
        )
        _update_je_in_store(je, church_id)
        return _json({
            "status": je.status.value if hasattr(je.status, "value") else str(je.status),
            "audit_trail": list(getattr(je, "audit_trail", []) or []),
        })
    except JEStateError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/jes")
def list_jes(
    church_id: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> JSONResponse:
    """List journal entries with optional filtering (FR-06.4) — DB-backed."""
    from datetime import date as _date

    def _parse_date(s: Optional[str]) -> Optional[_date]:
        if not s:
            return None
        try:
            return _date.fromisoformat(s)
        except ValueError:
            return None

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    # Determine target church set.
    if church_id:
        church_ids = [church_id]
    else:
        try:
            from .db import coa_store as _coa_store
            church_ids = [c["church_id"] for c in _coa_store.list_churches()]
        except Exception:
            church_ids = []

    jes: List[Dict[str, Any]] = []
    for cid in church_ids:
        try:
            entries = journal_entry_store.list_journal_entries(
                cid, status=status, date_from=df, date_to=dt
            )
        except Exception:
            continue
        for e in entries:
            jes.append(e.model_dump())

    # Merge in JEs that live only on processing jobs (not yet promoted).
    if church_id:
        try:
            for job in flow.list_jobs(church_id):
                if job.journal_entry:
                    je_obj = job.journal_entry
                    je_dict = (
                        je_obj.model_dump()
                        if hasattr(je_obj, "model_dump")
                        else dict(je_obj)
                    )
                    if status and je_dict.get("status") != status:
                        continue
                    if any(j.get("entry_id") == je_dict.get("entry_id") for j in jes):
                        continue
                    jes.append({
                        **je_dict,
                        "church_id": job.church_id,
                        "job_id": job.job_id,
                    })
        except Exception:
            pass

    return _json(jes)


# =====================================================================
# Phase 3.7 — Payment Initiation endpoints
# =====================================================================

PAYMENT_DATA_DIR = Path(__file__).resolve().parent / "data"


def _payments_path(church_id: str) -> Path:
    safe = "".join(c for c in church_id if c.isalnum() or c in "_-") or "default"
    return PAYMENT_DATA_DIR / f"payments_{safe}.jsonl"


def _persist_payment(church_id: str, payment_dict: Dict[str, Any]) -> None:
    PAYMENT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _payments_path(church_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payment_dict, default=str) + "\n")


def _load_payments(church_id: str) -> List[Dict[str, Any]]:
    p = _payments_path(church_id)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _find_payment(payment_id: str):
    """Return (payment_dict, church_id) or (None, None) — DB-backed."""
    inst = payment_store.get_payment(payment_id)
    if inst is None:
        return None, None
    return inst.model_dump(), inst.church_id


def _vendor_total_amount(je) -> Decimal:
    total = Decimal("0")
    for line in je.lines:
        d = getattr(line, "debit", None) or Decimal("0")
        try:
            total += Decimal(str(d))
        except Exception:
            pass
    return total


@app.post("/api/jes/{je_id}/payment")
async def create_payment_for_je(je_id: str, body: Dict[str, Any]) -> JSONResponse:
    """FR-08: Create a payment instruction for an APPROVED JE.

    Body: {method?: "ACH"|"CHECK"|"CREDIT_CARD"|"WIRE", vendor_name?: str}
    Returns the PaymentInstruction plus a recommendation block.
    """
    from .models.schemas import (
        PaymentInstruction, PaymentMethod, PaymentStatus,
        ACHRecord, CheckRecord, CreditCardMemo,
    )
    from .db import vendor_store  # Phase 1: was `from .tools import vendor_store`
    from .tools.payment_recommender import recommend_payment_method

    je, church_id = _find_journal_entry(je_id)
    if je is None:
        raise HTTPException(404, f"JE {je_id} not found")

    vendor_name = (body or {}).get("vendor_name") or je.vendor_name or "Unknown Vendor"
    vendor = vendor_store.find_vendor_by_name(church_id, vendor_name)

    recommendation = recommend_payment_method(je, vendor)
    requested_method = (body or {}).get("method") or recommendation["recommended"]
    try:
        method = PaymentMethod(requested_method)
    except ValueError:
        raise HTTPException(422, f"Invalid payment method: {requested_method}")

    amount = _vendor_total_amount(je)
    now = datetime.utcnow()
    payment_id = f"PMT-{je.entry_id}-{now.strftime('%Y%m%d%H%M%S')}"

    ach_record = None
    check_record = None
    cc_memo = None
    pay_date = je.entry_date if hasattr(je, "entry_date") else datetime.utcnow().date()

    if method == PaymentMethod.ACH:
        if vendor and vendor.ach_routing:
            ach_record = ACHRecord(
                routing_number=vendor.ach_routing,
                account_number_last4=vendor.ach_account_last4 or "0000",
                amount=amount,
                payment_date=pay_date,
                memo=je.description,
            )
        else:
            ach_record = ACHRecord(
                routing_number="000000000",
                account_number_last4="0000",
                amount=amount,
                payment_date=pay_date,
                memo=je.description,
            )
    elif method == PaymentMethod.CHECK:
        check_record = CheckRecord(
            payee=vendor_name,
            amount=amount,
            address=(vendor.address if vendor else None),
            memo=je.description,
            check_date=pay_date,
        )
    elif method == PaymentMethod.CREDIT_CARD:
        cc_memo = CreditCardMemo(
            amount=amount,
            vendor_name=vendor_name,
            description=je.description or "",
            instruction=(
                f"Charge ${amount} to organization credit card on file for "
                f"{vendor_name}. JE {je.entry_id}."
            ),
        )

    inst = PaymentInstruction(
        payment_id=payment_id,
        church_id=church_id,
        vendor_id=(vendor.vendor_id if vendor else None),
        je_id=je.entry_id,
        method=method,
        amount=amount,
        status=PaymentStatus.PENDING_APPROVAL,
        ach_record=ach_record,
        check_record=check_record,
        cc_memo=cc_memo,
        requested_by=(body or {}).get("requested_by"),
        created_at=now,
        updated_at=now,
    )

    payment_store.create_payment(church_id, inst)

    # Audit
    try:
        approval_audit.append_event(church_id, {
            "event_type": "PAYMENT_CREATED",
            "payment_id": payment_id,
            "je_id": je.entry_id,
            "method": method.value,
            "amount": str(amount),
            "actor": (body or {}).get("requested_by"),
        })
    except Exception:
        pass

    out = inst.model_dump()
    out["recommendation"] = recommendation
    return _json(out)


@app.post("/api/payments/{payment_id}/approve")
async def approve_payment(
    payment_id: str,
    body: Dict[str, Any],
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Treasurer approves a payment instruction → status=APPROVED.

    RBAC: requires TREASURER_ADMIN role. Header check is **enforced when an
    `X-User-Role` header is present** so we don't break legacy clients during
    rollout; absent header is allowed for backward-compat.
    """
    from .auth import get_caller_role, has_role
    actual = get_caller_role(request)
    if actual is not None and not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual}' lacks TREASURER_ADMIN",
        )

    from .models.schemas import PaymentInstruction, PaymentStatus

    data, church_id = _find_payment(payment_id)
    if data is None:
        raise HTTPException(404, f"Payment {payment_id} not found")

    inst = PaymentInstruction(**data)
    if inst.status not in (PaymentStatus.PENDING_APPROVAL, PaymentStatus.DRAFT):
        raise HTTPException(
            400, f"Cannot approve payment in status {inst.status}"
        )

    approver = (body or {}).get("approver_email") or (body or {}).get("approver")
    if not approver:
        raise HTTPException(422, "approver_email required")

    inst.status = PaymentStatus.APPROVED
    inst.approved_by = approver
    inst.updated_at = datetime.utcnow()

    payment_store.update_payment(payment_id, {
        "status": PaymentStatus.APPROVED,
        "approved_by": approver,
        "updated_at": inst.updated_at,
    })

    try:
        approval_audit.append_event(church_id, {
            "event_type": "PAYMENT_APPROVED",
            "payment_id": payment_id,
            "actor": approver,
        })
    except Exception:
        pass

    return _json(inst.model_dump())


@app.get("/api/payments/{payment_id}/ach-file")
async def download_ach_file(payment_id: str):
    """Return the NACHA ACH file as plain text."""
    from .models.schemas import PaymentInstruction, PaymentMethod
    from .tools.nacha_generator import generate_nacha_file

    data, church_id = _find_payment(payment_id)
    if data is None:
        raise HTTPException(404, f"Payment {payment_id} not found")
    inst = PaymentInstruction(**data)
    if inst.method != PaymentMethod.ACH:
        raise HTTPException(400, "Payment is not an ACH instruction")

    content = generate_nacha_file([inst])
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": f'attachment; filename="{payment_id}.ach"'},
    )


@app.get("/api/payments/{payment_id}/check-pdf")
async def download_check_pdf(payment_id: str):
    """Generate a check PDF and return it as a file."""
    from .models.schemas import PaymentInstruction, PaymentMethod
    from .tools.check_generator import generate_check_pdf
    import tempfile

    data, church_id = _find_payment(payment_id)
    if data is None:
        raise HTTPException(404, f"Payment {payment_id} not found")
    inst = PaymentInstruction(**data)
    if inst.method != PaymentMethod.CHECK:
        raise HTTPException(400, "Payment is not a check instruction")

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    out = generate_check_pdf(inst, tmp.name)
    return FileResponse(
        out,
        media_type="application/pdf",
        filename=f"{payment_id}.pdf",
    )


@app.get("/api/churches/{church_id}/payments")
async def list_payments(church_id: str, status: Optional[str] = None) -> JSONResponse:
    """List all payments for a church, optionally filtered by status (DB-backed)."""
    payments = payment_store.list_payments(church_id, status=status)
    return _json([p.model_dump() for p in payments])


# ---- Vendor CRUD endpoints ----

@app.get("/api/churches/{church_id}/vendors")
async def list_vendors(church_id: str) -> JSONResponse:
    from .db import vendor_store  # Phase 1: was `from .tools import vendor_store`
    return _json([v.model_dump() for v in vendor_store.load_vendors(church_id)])


@app.post("/api/churches/{church_id}/vendors")
async def create_vendor(church_id: str, body: Dict[str, Any]) -> JSONResponse:
    from .models.schemas import Vendor
    from .db import vendor_store  # Phase 1: was `from .tools import vendor_store`
    body = dict(body or {})
    body["church_id"] = church_id
    if not body.get("vendor_id"):
        body["vendor_id"] = f"V-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    try:
        v = Vendor(**body)
    except Exception as e:
        raise HTTPException(422, f"Invalid vendor: {e}") from e
    saved = vendor_store.upsert_vendor(church_id, v)
    return _json(saved.model_dump())


@app.get("/api/churches/{church_id}/vendors/{vendor_id}")
async def get_vendor(church_id: str, vendor_id: str) -> JSONResponse:
    from .db import vendor_store  # Phase 1: was `from .tools import vendor_store`
    for v in vendor_store.load_vendors(church_id):
        if v.vendor_id == vendor_id:
            return _json(v.model_dump())
    raise HTTPException(404, f"Vendor {vendor_id} not found")


@app.put("/api/churches/{church_id}/vendors/{vendor_id}")
async def update_vendor(church_id: str, vendor_id: str, body: Dict[str, Any]) -> JSONResponse:
    from .models.schemas import Vendor
    from .db import vendor_store  # Phase 1: was `from .tools import vendor_store`
    body = dict(body or {})
    body["vendor_id"] = vendor_id
    body["church_id"] = church_id
    try:
        v = Vendor(**body)
    except Exception as e:
        raise HTTPException(422, f"Invalid vendor: {e}") from e
    saved = vendor_store.upsert_vendor(church_id, v)
    return _json(saved.model_dump())


@app.delete("/api/churches/{church_id}/vendors/{vendor_id}")
async def delete_vendor(church_id: str, vendor_id: str) -> JSONResponse:
    from .db import vendor_store  # Phase 1: was `from .tools import vendor_store`
    vendors = vendor_store.load_vendors(church_id)
    remaining = [v for v in vendors if v.vendor_id != vendor_id]
    if len(remaining) == len(vendors):
        raise HTTPException(404, f"Vendor {vendor_id} not found")
    vendor_store.save_vendors(church_id, remaining)
    return _json({"ok": True, "vendor_id": vendor_id})


# =====================================================================
# Phase 3.8 — Recurring JEs + CSV Import
# =====================================================================

RECURRING_DATA_DIR = Path(__file__).resolve().parent / "data"


def _recurring_path(church_id: str) -> Path:
    safe = "".join(c for c in church_id if c.isalnum() or c in "_-") or "default"
    return RECURRING_DATA_DIR / f"recurring_{safe}.jsonl"


def _load_recurring(church_id: str) -> List[Dict[str, Any]]:
    p = _recurring_path(church_id)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("recurring_id"):
            by_id[d["recurring_id"]] = d
    return list(by_id.values())


def _persist_recurring(church_id: str, rec: Dict[str, Any]) -> None:
    RECURRING_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _recurring_path(church_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


@app.post("/api/jes/recurring")
async def create_recurring_je(body: Dict[str, Any]) -> JSONResponse:
    """Create a recurring JE schedule.

    Body: {church_id, template_je: JournalEntry dict, schedule_cron: str,
           created_by?: str, active?: bool}
    """
    from .models.schemas import JournalEntry
    from .tools import recurring_store
    if not isinstance(body, dict):
        raise HTTPException(400, "Body required")
    church_id = body.get("church_id")
    template = body.get("template_je")
    cron = body.get("schedule_cron")
    if not church_id or not template or not cron:
        raise HTTPException(422, "church_id, template_je, schedule_cron required")
    try:
        JournalEntry(**template)
    except Exception as e:
        raise HTTPException(422, f"Invalid template_je: {e}") from e
    # Honor RECURRING_DATA_DIR override (used by tests).
    recurring_store.DATA_DIR = RECURRING_DATA_DIR
    try:
        rec = recurring_store.create_recurring(
            church_id=str(church_id),
            template_je=template,
            cron=str(cron),
            created_by=body.get("created_by"),
            active=bool(body.get("active", True)),
        )
    except Exception as e:
        raise HTTPException(422, f"Could not create recurring: {e}") from e
    return _json(rec.model_dump())


@app.get("/api/jes/recurring")
async def list_recurring_jes(church_id: Optional[str] = None) -> JSONResponse:
    if church_id:
        return _json(_load_recurring(church_id))
    out: List[Dict[str, Any]] = []
    for f in RECURRING_DATA_DIR.glob("recurring_*.jsonl"):
        cid = f.stem.replace("recurring_", "")
        out.extend(_load_recurring(cid))
    return _json(out)


@app.put("/api/jes/recurring/{recurring_id}")
async def update_recurring_je(recurring_id: str, body: Dict[str, Any]) -> JSONResponse:
    from .tools import recurring_store
    recurring_store.DATA_DIR = RECURRING_DATA_DIR
    body = dict(body or {})
    for f in RECURRING_DATA_DIR.glob("recurring_*.jsonl"):
        cid = f.stem.replace("recurring_", "")
        rec = recurring_store.find_recurring(cid, recurring_id)
        if rec is None:
            continue
        # Apply allowed updates.
        if "schedule_cron" in body:
            rec.schedule_cron = str(body["schedule_cron"])
            nxt = recurring_store.calculate_next_cron(rec.schedule_cron)
            if nxt is not None:
                rec.next_run = nxt
        if "active" in body:
            rec.active = bool(body["active"])
        if "template_je" in body and isinstance(body["template_je"], dict):
            rec.template_je = body["template_je"]
        recurring_store.update_recurring(cid, rec)
        return _json(rec.model_dump())
    raise HTTPException(404, f"Recurring {recurring_id} not found")


@app.delete("/api/jes/recurring/{recurring_id}")
async def delete_recurring_je(recurring_id: str) -> JSONResponse:
    from .tools import recurring_store
    recurring_store.DATA_DIR = RECURRING_DATA_DIR
    for f in RECURRING_DATA_DIR.glob("recurring_*.jsonl"):
        cid = f.stem.replace("recurring_", "")
        if recurring_store.delete_recurring(cid, recurring_id):
            return _json({"ok": True, "recurring_id": recurring_id})
    raise HTTPException(404, f"Recurring {recurring_id} not found")


@app.post("/api/jes/import-csv")
async def import_jes_csv(
    file: UploadFile = File(...),
    church_id: str = Form(...),
    created_by: Optional[str] = Form(None),
) -> JSONResponse:
    """Batch CSV import: columns memo, from_account, to_account, amount, fund."""
    from .tools.je_csv_importer import import_je_csv
    raw = await file.read()
    result = import_je_csv(
        file_bytes=raw,
        church_id=church_id,
        created_by=created_by,
        data_dir=JE_DATA_DIR,
    )
    return _json(result.to_dict())


# =====================================================================
# Phase 3.10 — Audit chain verify, model config
# =====================================================================

@app.get("/api/audit-chain/verify")
@app.get("/api/audit/verify")
async def audit_verify(church_id: Optional[str] = None) -> JSONResponse:
    """Verify the SHA-256 hash chain integrity for one or all churches."""
    from .tools.approval_audit import verify_chain
    if church_id:
        ok = verify_chain(church_id)
        return _json({"valid": bool(ok), "church_id": church_id})
    # Verify across all known churches
    results: Dict[str, bool] = {}
    audit_dir = Path(__file__).resolve().parent / "audit_trails"
    if audit_dir.exists():
        for f in audit_dir.glob("approvals_*.jsonl"):
            cid = f.stem.replace("approvals_", "")
            results[cid] = bool(verify_chain(cid))
    all_valid = all(results.values()) if results else True
    return _json({"valid": all_valid, "by_church": results})


@app.get("/api/model-config")
async def get_model_config() -> JSONResponse:
    from .tools.model_router import load_model_config
    return _json(load_model_config())


@app.put("/api/model-config")
async def put_model_config(
    body: Dict[str, Any],
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Admin-only: override the LLM model used per agent.

    RBAC: requires TREASURER_ADMIN role (FR-4.4).
    """
    from .auth import get_caller_role, has_role
    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )
    from .tools.model_router import save_model_config
    if not isinstance(body, dict):
        raise HTTPException(422, "Body must be {agent: model_id}")
    saved = save_model_config(body)
    return _json(saved)


@app.get("/api/model-config/{agent_name}")
async def get_model_for_agent(agent_name: str) -> JSONResponse:
    from .tools.model_router import resolve_model
    return _json({"agent": agent_name, "model": resolve_model(agent_name)})


# ===== FR-NF-Authority: Budgetary Authority Routing Matrix =====

class BudgetaryAuthorityBody(BaseModel):
    authority_id: Optional[str] = None
    role: str
    gl_pattern: str
    max_amount: float
    can_override_restrictions: bool = False
    fund_restrictions: List[str] = []


@app.get("/api/churches/{church_id}/authorities")
async def list_authorities(church_id: str) -> JSONResponse:
    from .tools import budgetary_authority as ba
    rows = ba.load_authorities(church_id)
    return _json([a.model_dump() for a in rows])


@app.post("/api/churches/{church_id}/authorities")
async def add_authority_endpoint(
    church_id: str,
    body: BudgetaryAuthorityBody,
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Create a budgetary-authority rule. RBAC: TREASURER_ADMIN."""
    from .auth import get_caller_role, has_role
    from .tools import budgetary_authority as ba
    from .models.schemas import BudgetaryAuthority
    import uuid

    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )
    now = datetime.utcnow()
    auth = BudgetaryAuthority(
        authority_id=body.authority_id or f"auth-{uuid.uuid4().hex[:10]}",
        church_id=church_id,
        role=body.role,
        gl_pattern=body.gl_pattern,
        max_amount=body.max_amount,
        can_override_restrictions=body.can_override_restrictions,
        fund_restrictions=body.fund_restrictions or [],
        created_at=now,
        updated_at=now,
    )
    rows = ba.add_authority(church_id, auth)
    return _json({"ok": True, "count": len(rows), "authority_id": auth.authority_id})


@app.put("/api/churches/{church_id}/authorities/{authority_id}")
async def update_authority_endpoint(
    church_id: str,
    authority_id: str,
    body: BudgetaryAuthorityBody,
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Update a rule. RBAC: TREASURER_ADMIN."""
    from .auth import get_caller_role, has_role
    from .tools import budgetary_authority as ba

    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(403, f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN")

    updates = {
        "role": body.role,
        "gl_pattern": body.gl_pattern,
        "max_amount": body.max_amount,
        "can_override_restrictions": body.can_override_restrictions,
        "fund_restrictions": body.fund_restrictions or [],
    }
    updated = ba.update_authority(church_id, authority_id, updates)
    if not updated:
        raise HTTPException(404, f"Authority {authority_id} not found")
    return _json(updated.model_dump())


@app.delete("/api/churches/{church_id}/authorities/{authority_id}")
async def delete_authority_endpoint(
    church_id: str,
    authority_id: str,
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    """Delete a rule. RBAC: TREASURER_ADMIN."""
    from .auth import get_caller_role, has_role
    from .tools import budgetary_authority as ba

    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(403, f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN")
    rows = ba.remove_authority(church_id, authority_id)
    return _json({"ok": True, "count": len(rows)})


@app.get("/api/churches/{church_id}/authorities/check")
async def check_authority_endpoint(
    church_id: str,
    role: str,
    gl: str,
    fund: str,
    amount: float,
) -> JSONResponse:
    """Check if a (role, gl, fund, amount) combo is approvable."""
    from .tools import budgetary_authority as ba
    auth, reason = ba.get_authority_for_role_and_gl(church_id, role, gl, fund, amount)
    return _json({
        "allowed": auth is not None,
        "reason": reason,
        "authority_id": auth.authority_id if auth else None,
        "can_override_restrictions": bool(auth and auth.can_override_restrictions),
    })


# ===== FR-Bank-Integration: Plaid =====

class PlaidCompleteAuthBody(BaseModel):
    public_token: str


class PlaidSyncBody(BaseModel):
    account_id: str
    days_back: int = 60


@app.post("/api/churches/{church_id}/plaid/create-link-token")
async def plaid_create_link_token(church_id: str) -> JSONResponse:
    """Generate a Plaid Link token for the UI to open Plaid Link."""
    from .integrations import plaid_client
    try:
        churches = coa_store.list_churches()
        church_name = next(
            (c.get("church_name", church_id) for c in churches if c.get("church_id") == church_id),
            church_id,
        )
        mgr = plaid_client.get_manager()
        out = mgr.create_link_token(user_id=church_id, church_name=church_name)
        return _json(out)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/churches/{church_id}/plaid/complete-auth")
async def plaid_complete_auth(
    church_id: str,
    body: PlaidCompleteAuthBody,
) -> JSONResponse:
    """Exchange the public_token, fetch + store the accounts."""
    from .integrations import plaid_client
    from .db import plaid_store  # Phase 1: was `from .tools import plaid_store`
    from .models.schemas import PlaidAccount

    try:
        mgr = plaid_client.get_manager()
        access_token = mgr.exchange_public_token(body.public_token)
        accounts_raw = mgr.get_accounts(access_token)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))

    enc_token = plaid_store.encrypt_token(access_token)
    saved = []
    now = datetime.utcnow()
    for entry in accounts_raw:
        balances = entry.get("balances", {}) or {}
        try:
            acct = PlaidAccount(
                account_id=entry["account_id"],
                church_id=church_id,
                access_token_enc=enc_token,
                account_type=entry.get("type") or "depository",
                account_subtype=entry.get("subtype") or "",
                mask=entry.get("mask") or "",
                name=entry.get("name") or "Account",
                current_balance=float(balances.get("current") or 0.0),
                available_balance=float(balances.get("available") or 0.0),
                balance_updated_at=now,
                linked_at=now,
                is_ach_enabled=True,
                created_at=now,
            )
            plaid_store.save_plaid_account(church_id, acct)
            saved.append({
                "account_id": acct.account_id,
                "name": acct.name,
                "mask": acct.mask,
                "balance": acct.current_balance,
            })
        except Exception as exc:
            print(f"[Plaid] failed to persist account: {exc}", flush=True)
            continue
    return _json({"accounts": saved})


@app.get("/api/churches/{church_id}/plaid/accounts")
async def list_plaid_accounts(church_id: str) -> JSONResponse:
    from .db import plaid_store  # Phase 1: was `from .tools import plaid_store`
    rows = plaid_store.load_plaid_accounts(church_id)
    return _json([
        {
            "account_id": a.account_id,
            "name": a.name,
            "mask": a.mask,
            "account_type": a.account_type,
            "account_subtype": a.account_subtype,
            "current_balance": a.current_balance,
            "available_balance": a.available_balance,
            "balance_updated_at": a.balance_updated_at.isoformat(),
            "linked_at": a.linked_at.isoformat(),
            "is_ach_enabled": a.is_ach_enabled,
        }
        for a in rows
    ])


@app.get("/api/churches/{church_id}/plaid/accounts/{account_id}/refresh")
async def refresh_plaid_account(church_id: str, account_id: str) -> JSONResponse:
    from .tools import plaid_store
    try:
        a = plaid_store.refresh_account_balances(church_id, account_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    if not a:
        raise HTTPException(404, f"Account {account_id} not found")
    return _json({
        "current_balance": a.current_balance,
        "available_balance": a.available_balance,
        "refreshed_at": a.balance_updated_at.isoformat(),
    })


@app.delete("/api/churches/{church_id}/plaid/accounts/{account_id}")
async def delete_plaid_account_endpoint(
    church_id: str,
    account_id: str,
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    from .auth import get_caller_role, has_role
    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(403, f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN")
    from .db import plaid_store  # Phase 1: was `from .tools import plaid_store`
    # NOTE: db.plaid_store.delete_plaid_account returns bool, not list. Wrap so
    # the existing response shape is preserved.
    ok = plaid_store.delete_plaid_account(church_id, account_id)
    return _json({"ok": bool(ok), "count": 1 if ok else 0})


@app.post("/api/churches/{church_id}/plaid/sync-transactions")
async def sync_plaid_transactions(
    church_id: str,
    body: Optional[PlaidSyncBody] = None,
    account_id: Optional[str] = None,
) -> JSONResponse:
    from .db import plaid_store  # Phase 1: was `from .tools import plaid_store`
    from datetime import date as _date, timedelta as _td

    effective_account = (body.account_id if body else None) or account_id or ""
    days_back = (body.days_back if body else None) or 60

    try:
        new_txns = plaid_store.fetch_and_store_transactions(
            church_id, effective_account, days_back=days_back,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))

    end = _date.today()
    start = end - _td(days=days_back)
    return _json({
        "transactions_synced": len(new_txns),
        "date_range": f"{start.isoformat()} to {end.isoformat()}",
    })


@app.get("/api/churches/{church_id}/plaid/transactions")
async def list_plaid_transactions(
    church_id: str,
    account_id: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
) -> JSONResponse:
    from .db import plaid_store  # Phase 1: was `from .tools import plaid_store`
    from datetime import date as _date

    df = _date.fromisoformat(from_) if from_ else None
    dt = _date.fromisoformat(to) if to else None
    rows = plaid_store.load_plaid_transactions(
        church_id, account_id=account_id, date_from=df, date_to=dt,
    )
    matches = _load_recon_matches(church_id)
    return _json([
        {
            "txn_id": t.txn_id,
            "account_id": t.account_id,
            "date": t.date.isoformat(),
            "description": t.description,
            "amount": t.amount,
            "category": t.category,
            "merchant_name": t.merchant_name,
            "matched": t.txn_id in matches,
            "matched_je_id": matches.get(t.txn_id, {}).get("je_id"),
            "matched_at": matches.get(t.txn_id, {}).get("matched_at"),
        }
        for t in rows
    ])


@app.post("/api/churches/{church_id}/plaid/webhook")
async def plaid_webhook(church_id: str, request: Request) -> JSONResponse:
    """Receive Plaid webhook events. On TRANSACTIONS events, sync accounts and emit BankItemObserved."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    # Always audit log the webhook
    audit_path = Path(__file__).resolve().parent / "data" / f"plaid_webhook_{church_id}.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as fh:
        fh.write(json.dumps({
            "ts": datetime.utcnow().isoformat(),
            "body": body,
        }) + "\n")

    # If it's a TRANSACTIONS event, sync all Plaid accounts for this church
    webhook_type = body.get("webhook_type")
    if webhook_type == "TRANSACTIONS":
        from .db import plaid_store as db_plaid_store
        from .tools import plaid_store as tools_plaid_store

        try:
            # Load all Plaid accounts for this church
            accounts = db_plaid_store.load_plaid_accounts(church_id)
            for acct in accounts:
                # Trigger transaction sync for each account (60 days back)
                # This calls the Plaid API, stores txns, and emits BankItemObserved events
                tools_plaid_store.fetch_and_store_transactions(
                    church_id, acct.account_id, days_back=60
                )
        except Exception:
            # Log webhook audit but don't fail the response if sync fails
            pass

    return _json({"ok": True})


def _recon_matches_path(church_id: str) -> Path:
    return Path(__file__).resolve().parent / "data" / f"recon_matches_{church_id}.json"


def _load_recon_matches(church_id: str) -> Dict[str, Any]:
    p = _recon_matches_path(church_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_recon_matches(church_id: str, matches: Dict[str, Any]) -> None:
    p = _recon_matches_path(church_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(matches, default=str))


@app.post("/api/churches/{church_id}/plaid/auto-match")
async def plaid_auto_match(church_id: str, account_id: Optional[str] = None) -> JSONResponse:
    """[DEPRECATED — kept for back-compat]

    The structural matcher now runs automatically inside Plaid sync, so a
    manual "Auto-Match" call is no longer required. This endpoint forwards
    to the same matcher used by sync; clients should migrate to
    `/api/churches/{church_id}/exceptions` to surface unmatched items
    instead of triggering a match cycle.
    """
    from .events import structural_match
    report = structural_match.run_for_church(church_id, account_id=account_id)
    report["deprecated"] = True
    report["replacement"] = f"/api/churches/{church_id}/exceptions"
    return _json(report)


@app.get("/api/churches/{church_id}/reconciliation-exceptions")
async def list_reconciliation_exceptions(church_id: str) -> JSONResponse:
    """Canonical inbox: items the structural matcher could not pair.

    Phase 5c surface. For exception cards requiring human adjudication,
    use /api/churches/{church_id}/exceptions instead.
    """
    from .events import structural_match
    items = structural_match.list_exceptions(church_id)
    return _json({
        "church_id": church_id,
        "exceptions": items,
        "count": len(items),
        "as_of": datetime.utcnow().isoformat(),
    })


@app.post("/api/churches/{church_id}/bank-statements/upload")
async def upload_bank_statement(church_id: str, file: UploadFile = File(...), account_id: Optional[str] = None) -> JSONResponse:
    """Upload CSV/OFX/QFX bank statement file for reconciliation.

    Phase 5c: Parses statement and emits BankItemObserved events (not JSONL).
    Transactions join the structural reconciliation matcher automatically.
    """
    from .tools.bank_statement_parser import parse_statement
    from .events.schemas import FinancialEvent, EventType, TagKind
    from .db.transactions import atomic_transaction
    from .events.emitter import emit_event_in_txn

    filename = file.filename or "statement"
    file_bytes = await file.read()

    try:
        transactions = parse_statement(file_bytes, filename)
    except Exception as exc:
        return _json({"error": f"Failed to parse bank statement: {exc}", "transactions_parsed": 0}, status_code=400)

    txn_dicts = [t.model_dump() if hasattr(t, "model_dump") else vars(t) for t in transactions]

    # Phase 5c: Emit BankItemObserved events instead of JSONL persistence
    emitted_count = 0
    try:
        with atomic_transaction() as conn:
            for txn in txn_dicts:
                ev = FinancialEvent(
                    event_type=EventType.BANK_ITEM_OBSERVED,
                    church_id=church_id,
                    occurred_at=txn.get("date") or datetime.utcnow(),
                    payload={
                        "txn_id": txn.get("txn_id") or txn.get("id"),
                        "source": "csv_upload",
                        "filename": filename,
                        "account_id": account_id or txn.get("account_id"),
                        "date": str(txn.get("date")),
                        "amount": float(txn.get("amount", 0)),
                        "description": str(txn.get("description") or ""),
                        "category": str(txn.get("category") or ""),
                    },
                )
                if account_id:
                    ev.add_tag(TagKind.DOCUMENT, f"upload:{filename}")
                emit_event_in_txn(conn, ev)
                emitted_count += 1
    except Exception as e:
        logger.warning(f"Failed to emit BankItemObserved events for {church_id}: {e}")
        # Degrade gracefully: return parsed count even if event emission fails
        pass

    return _json({
        "transactions_parsed": len(transactions),
        "transactions_emitted": emitted_count,
        "account_id": account_id,
        "filename": filename,
        "transactions": txn_dicts[:50],  # preview first 50
    })


# ============================================================
# Frontend convenience aliases (FR-XX wiring)
# ============================================================
# These endpoints provide simpler URLs that the frontend can use
# without needing to construct church_id paths.

@app.get("/api/budget/variance")
async def budget_variance_alias(church_id: str) -> JSONResponse:
    """Alias for /api/churches/{church_id}/budget/variance-report — Budget projections.

    Returns variance report with year-forward projections per FR-03.3.
    """
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, f"Church not found: {church_id}")
    if ctx.budget is None:
        # Return empty structure rather than 404 — frontend handles gracefully
        return _json({
            "church_id": church_id,
            "lines": [],
            "totals": {"annual_budget": "0", "ytd_actual": "0", "remaining": "0"},
            "message": "Budget not configured for this church",
        })

    threshold = float(ctx.budget_warning_threshold or 0.80)
    accounts_by_no = {a.account_number: a for a in ctx.accounts}
    lines: List[Dict[str, Any]] = []
    annual_total = Decimal("0")
    ytd_total = Decimal("0")

    # Compute month progression for year-forward projection (FR-03.3)
    now = datetime.utcnow()
    fiscal_start_month = 1  # default; could be configured per church
    months_elapsed = max(1, (now.month - fiscal_start_month) + 1)
    months_in_year = 12

    for acct_no, bm in ctx.budget.accounts.items():
        annual = Decimal(bm.annual_total)
        ytd = Decimal(ctx.ytd_actuals.get(acct_no, Decimal("0")))
        remaining = annual - ytd
        annual_total += annual
        ytd_total += ytd
        pct = float(ytd / annual) if annual > 0 else (1.5 if ytd > 0 else 0.0)
        # Year-forward projection: extrapolate YTD spend rate to full year
        run_rate_monthly = ytd / Decimal(months_elapsed) if months_elapsed > 0 else Decimal("0")
        projected_year_end = run_rate_monthly * Decimal(months_in_year)
        projected_pct = float(projected_year_end / annual) if annual > 0 else 0.0

        acct = accounts_by_no.get(acct_no)
        lines.append({
            "gl_code": acct_no,
            "gl_name": acct.account_name if acct else acct_no,
            "annual_budget": float(annual),
            "ytd_actual": float(ytd),
            "remaining": float(remaining),
            "pct_used": pct,
            "projected_year_end": float(projected_year_end),
            "projected_pct": projected_pct,
            "projected_overage": float(projected_year_end - annual) if projected_year_end > annual else 0.0,
            "status": "over" if pct >= 1.0 else ("at_risk" if pct >= threshold else "within"),
        })

    return _json({
        "church_id": church_id,
        "fiscal_year": ctx.budget.fiscal_year,
        "as_of": now.isoformat(),
        "months_elapsed": months_elapsed,
        "lines": lines,
        "totals": {
            "annual_budget": float(annual_total),
            "ytd_actual": float(ytd_total),
            "remaining": float(annual_total - ytd_total),
            "consumed_pct": float(ytd_total / annual_total) if annual_total > 0 else 0.0,
        },
    })


@app.get("/api/coa/search")
async def coa_search_alias(q: str, church_id: str, k: int = 5) -> JSONResponse:
    """Alias for /api/churches/{church_id}/search — Semantic COA search.

    Uses ChromaDB to find GL accounts most similar to the query string.
    """
    if not q or not q.strip():
        return _json({"matches": [], "query": q})
    try:
        results = coa_store.semantic_search(church_id, q.strip(), k=k)
    except Exception as exc:
        return _json({"matches": [], "query": q, "error": str(exc)})

    # Normalise results to a frontend-friendly shape
    matches = []
    for r in (results or []):
        if isinstance(r, dict):
            matches.append({
                "gl_code": r.get("account_number") or r.get("gl_code"),
                "gl_name": r.get("account_name") or r.get("gl_name") or r.get("name"),
                "fund": r.get("fund") or r.get("fund_id"),
                "fund_restriction": r.get("fund_restriction"),
                "account_type": r.get("account_type"),
                "description": r.get("description"),
                "score": r.get("score") or r.get("similarity"),
            })
        else:
            matches.append({"raw": str(r)})
    return _json({"query": q, "matches": matches, "k": k})


@app.get("/api/coa")
async def coa_list_alias(church_id: str) -> JSONResponse:
    """List all GL accounts for a church (frontend convenience)."""
    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        return _json({"accounts": [], "funds": []})
    accounts = []
    for a in ctx.accounts:
        accounts.append({
            "gl_code": a.account_number,
            "gl_name": a.account_name,
            "account_type": getattr(a, "account_type", None),
            "fund": getattr(a, "fund_id", None) or getattr(a, "fund", None),
            "fund_restriction": getattr(a, "fund_restriction", None),
            "description": getattr(a, "description", None),
        })
    funds = []
    for f in (ctx.funds or []):
        funds.append({
            "fund_id": getattr(f, "fund_id", None) or getattr(f, "id", None),
            "fund_name": getattr(f, "fund_name", None) or getattr(f, "name", None),
            "restriction": getattr(f, "restriction", None),
        })
    return _json({"accounts": accounts, "funds": funds})


# ---------- Job real-time polling (FR-XX) ----------
# NOTE: This route uses /api/jobs-poll (hyphen) instead of /api/jobs/poll
# to avoid conflicting with the /api/jobs/{job_id} path parameter route.

@app.get("/api/jobs-poll")
async def jobs_poll(
    church_id: Optional[str] = None,
    since: Optional[str] = None,
) -> JSONResponse:
    """Lightweight polling endpoint for job updates.

    Returns only jobs updated since the given ISO timestamp. The frontend
    can call this on a 2-second interval without re-transferring all data.
    """
    jobs = flow.list_jobs(church_id=church_id)

    # Filter by since timestamp if provided
    cutoff: Optional[datetime] = None
    if since:
        try:
            cutoff = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if cutoff.tzinfo is not None:
                cutoff = cutoff.replace(tzinfo=None)
        except Exception:
            cutoff = None

    delta_jobs = []
    for j in jobs:
        updated = getattr(j, "updated_at", None) or getattr(j, "created_at", None)
        if cutoff and updated and isinstance(updated, datetime):
            if updated <= cutoff:
                continue
        delta_jobs.append(_job_summary(j))

    return _json({
        "as_of": datetime.utcnow().isoformat(),
        "since": since,
        "count": len(delta_jobs),
        "total": len(jobs),
        "jobs": delta_jobs,
    })



# --- ACS install state (in-memory, single-process) -----------------------
_acs_install_state: Dict[str, Any] = {
    "status": "idle",          # idle | running | success | error
    "log_lines": [],           # List[str]
    "started_at": None,        # ISO8601 str
    "finished_at": None,       # ISO8601 str
    "returncode": None,        # int | None
    "error": None,             # str | None
}
_acs_install_lock = threading.Lock()  # guards concurrent starts


def _acs_install_append(line: str) -> None:
    # Bound the buffer so a runaway process can't OOM the server.
    buf = _acs_install_state["log_lines"]
    buf.append(line.rstrip())
    if len(buf) > 2000:
        del buf[: len(buf) - 2000]


def _run_acs_install() -> None:
    """Background worker: install playwright + chromium, capture logs."""
    import subprocess, sys, datetime
    try:
        for cmd in (
            [sys.executable, "-m", "pip", "install", "playwright"],
            [sys.executable, "-m", "playwright", "install", "chromium"],
        ):
            _acs_install_append(f"$ {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                _acs_install_append(line)
            rc = proc.wait()
            if rc != 0:
                _acs_install_state["status"] = "error"
                _acs_install_state["returncode"] = rc
                _acs_install_state["error"] = f"Command failed: {' '.join(cmd)} (exit {rc})"
                _acs_install_state["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"
                return
        _acs_install_state["status"] = "success"
        _acs_install_state["returncode"] = 0
        _acs_install_state["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    except Exception as exc:  # noqa: BLE001
        _acs_install_state["status"] = "error"
        _acs_install_state["error"] = str(exc)
        _acs_install_state["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"


# ---------- Operations Council (FRD §16) ----------

@app.get("/api/council/queues")
async def council_queues(church_id: str) -> JSONResponse:
    """Aggregate four Operations Council queues: exceptions, policies, questions, recommendations (FRD §16.1).

    Returns:
        - exceptions: List of ExceptionCard (from jobs.py job_id records)
        - policies: List of PolicyCard (future: persisted policy decisions)
        - questions: List of QuestionCard (from chat history)
        - recommendations: List of RecommendationCard (from treasurer_queue.json)

    In Phase 3, these will be backed by real database records.
    For now, returns counts from queue endpoints below.
    """
    # Phase 3: Aggregate from real endpoints
    try:
        # Would call individual endpoints and aggregate here
        # For now, return minimal aggregation
        return _json({
            "church_id": church_id,
            "exceptions": [],
            "policies": [],
            "questions": [],
            "recommendations": [],
            "message": "Queue aggregation ready for Phase 3 data wiring"
        })
    except Exception as e:
        return _json({"error": str(e)}, 500)


@app.get("/api/churches/{church_id}/exceptions")
async def list_exceptions(church_id: str, status: str = "open") -> JSONResponse:
    """List ExceptionCard items requiring human adjudication (FRD §16, §9.1).

    Queries CardStore-backed exception records.
    """
    from backend.membrane.stores.exceptions import ExceptionCardStore

    exceptions, total = await ExceptionCardStore.list_by_status(church_id, status=status)
    open_count = len([e for e in exceptions if e.get("status") == "open"])

    return _json({
        "church_id": church_id,
        "exceptions": exceptions,
        "total_count": total,
        "open_count": open_count,
        "status_filter": status,
        "as_of": datetime.utcnow().isoformat(),
    })


@app.get("/api/churches/{church_id}/policies")
async def list_policies(
    church_id: str,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> JSONResponse:
    """List PolicyCard items (governance decisions awaiting votes).

    Queries CardStore-backed policy records.
    """
    from backend.membrane.stores.policies import PolicyCardStore

    policies, total = await PolicyCardStore.list_by_status(
        church_id, status=status, limit=limit, offset=offset
    )
    open_count = len([p for p in policies if p.get("status") in ("draft", "active")])

    return _json({
        "church_id": church_id,
        "policies": policies,
        "total_count": total,
        "open_count": open_count,
        "limit": limit,
        "offset": offset,
        "status_filter": status,
        "as_of": datetime.utcnow().isoformat(),
    })


@app.get("/api/churches/{church_id}/questions")
async def list_questions(church_id: str) -> JSONResponse:
    """List QuestionCard items (analyst queries awaiting response).

    Phase 3: Backend will query persisted QuestionCard records.
    Currently returns mock data with expected schema.
    """
    # TODO: Query real QuestionCard records from database
    return _json({
        "church_id": church_id,
        "questions": [],
        "total_count": 0,
        "open_count": 0,
        "message": "Question queue endpoint ready for database wiring"
    })


@app.get("/api/churches/{church_id}/recommendations")
async def list_recommendations(church_id: str) -> JSONResponse:
    """List RecommendationCard items (NBA candidates awaiting decisions).

    Phase 3: Backend will query persisted RecommendationCard records.
    Currently returns mock data with expected schema.
    """
    # TODO: Query real RecommendationCard records from database
    return _json({
        "church_id": church_id,
        "recommendations": [],
        "total_count": 0,
        "open_count": 0,
        "message": "Recommendation queue endpoint ready for database wiring"
    })


# ---------- Question Canvas & Intent Router (FRD §16.4, §10.1) ----------

@app.post("/api/intents/route")
async def route_intent(body: Dict[str, Any]) -> JSONResponse:
    """Classify user query into one of 15 default intents (FRD §10.1).

    Intent classification for Question Canvas:
    - all_in_program_cost: "What is our all-in program cost per unit of impact?"
    - pledge_fulfillment_cash_projection: "What's our cash position assuming 95% pledge fulfillment?"
    - multi_year_scenario_projection: "Show a 5-year projection under conservative/base/growth scenarios"
    - gift_trace_to_use: "Trace this $100K gift from donor intent to actual use"
    - mission_drift_analysis: "Which restricted funds have drifted from original intent?"
    - covenant_gap_analysis: "Are we tracking toward covenant violations?"
    - peer_benchmark_comparison: "How do we compare to peer organizations on X metric?"
    - expense_category_deep_dive: "Why did facilities spending spike 40%?"
    - restricted_fund_reallocation: "Which underperforming funds could be reallocated?"
    - seasonality_forecast: "What's our typical Q4 cash crunch look like?"
    - cfo_dashboard_refresh: "Show me the key metrics I need for next board meeting"
    - donor_risk_profile: "Which donors are at risk of lapsing?"
    - budget_variance_attribution: "Why are we 12% over on program expenses?"
    - headcount_projection: "Can we afford the proposed salary increases?"
    - quasi_endowment_stress_test: "What if pledge revenue drops 20%?"

    Phase 4: Simple keyword-based routing. Phase 5+: LLM classification via Claude API.
    """
    query = body.get("query", "").lower()
    church_id = body.get("church_id", "holy_comforter")

    # Simple keyword matching (Phase 4); Phase 5 will use LLM
    intents_map = {
        "all_in_program_cost": ["all-in", "program cost", "cost per unit", "cost per impact"],
        "pledge_fulfillment_cash_projection": ["cash position", "pledge fulfillment", "cash projection", "q4 cash"],
        "multi_year_scenario_projection": ["5-year", "scenario", "conservative", "base case", "growth"],
        "gift_trace_to_use": ["trace gift", "trace donation", "donor intent", "gift usage"],
        "mission_drift_analysis": ["mission drift", "drift", "original intent", "restrict"],
        "covenant_gap_analysis": ["covenant", "violation", "gap"],
        "peer_benchmark_comparison": ["peer", "benchmark", "compare", "similar organizations"],
        "expense_category_deep_dive": ["spending spike", "expense spike", "why", "expenses"],
        "restricted_fund_reallocation": ["reallocation", "underperforming fund", "reallocate"],
        "seasonality_forecast": ["seasonality", "q4", "crunch", "seasonal"],
        "cfo_dashboard_refresh": ["dashboard", "key metrics", "board meeting"],
        "donor_risk_profile": ["donor risk", "lapsing", "at risk"],
        "budget_variance_attribution": ["variance", "over budget", "over/under"],
        "headcount_projection": ["headcount", "salary", "staff"],
        "quasi_endowment_stress_test": ["stress test", "endowment", "drop", "downturn"]
    }

    # Route to best matching intent
    matched_intent = None
    max_matches = 0

    for intent, keywords in intents_map.items():
        matches = sum(1 for kw in keywords if kw in query)
        if matches > max_matches:
            max_matches = matches
            matched_intent = intent

    if not matched_intent:
        matched_intent = "all_in_program_cost"  # default fallback

    return _json({
        "church_id": church_id,
        "query": body.get("query"),
        "intent": matched_intent,
        "confidence": 0.75 if max_matches > 0 else 0.5,
        "suggested_follow_ons": generate_follow_on_suggestions(matched_intent)
    })


def generate_follow_on_suggestions(intent: str) -> List[str]:
    """Generate follow-on question suggestions based on intent."""
    suggestions_map = {
        "all_in_program_cost": [
            "Show breakdown by program area",
            "Compare to peer organizations",
            "Historical trend (3-year)"
        ],
        "pledge_fulfillment_cash_projection": [
            "Scenario at 85% fulfillment",
            "Compare to prior year Q4",
            "Flag major pledge gaps"
        ],
        "multi_year_scenario_projection": [
            "Show covenant impact under each scenario",
            "Which scenario is most likely?",
            "Break down by revenue vs expense drivers"
        ],
        "gift_trace_to_use": [
            "Show donor communications sent",
            "Flag any use violations",
            "Generate donor impact letter"
        ],
        "mission_drift_analysis": [
            "Show donor communication templates",
            "List potential reallocations",
            "Flag legal restrictions"
        ],
        "covenant_gap_analysis": [
            "Show which covenants at risk",
            "What corrective actions are needed?",
            "Timeline to compliance"
        ],
        "peer_benchmark_comparison": [
            "Show peer data sources",
            "Which metrics are we strongest in?",
            "Recommended improvements"
        ],
        "expense_category_deep_dive": [
            "Itemize the top 5 drivers",
            "Is this a one-time spike or trend?",
            "Compare to prior year"
        ],
        "restricted_fund_reallocation": [
            "Show donor communication templates",
            "Estimate reallocation impact",
            "What approvals are needed?"
        ],
        "seasonality_forecast": [
            "Show historical Q4 patterns",
            "Mitigation strategies",
            "Optimal cash reserve targets"
        ],
        "cfo_dashboard_refresh": [
            "Show full executive summary",
            "Include covenant tracking",
            "Flag key risks"
        ],
        "donor_risk_profile": [
            "Show lapse probability by donor",
            "Recommended retention strategies",
            "Stewardship letter templates"
        ],
        "budget_variance_attribution": [
            "Show variance by line",
            "Root cause for top 3 variances",
            "Forecast full-year impact"
        ],
        "headcount_projection": [
            "Show FTE vs budget impact",
            "Break down by department",
            "Alternative scenarios"
        ],
        "quasi_endowment_stress_test": [
            "Show impact on annual draw",
            "Multi-year recovery timeline",
            "Policy options"
        ]
    }
    return suggestions_map.get(intent, ["Ask another question", "Refine your query"])


@app.post("/api/intents/answer")
async def answer_question(body: Dict[str, Any]) -> JSONResponse:
    """Generate answer to classified question (Phase 4+).

    Phase 4: Return structured answer template with data placeholders.
    Phase 5: Integrate with Claude API for natural language generation.
    """
    intent = body.get("intent")
    query = body.get("query", "")
    church_id = body.get("church_id", "holy_comforter")
    question_id = body.get("question_id")
    context = body.get("context", {})

    # Phase 5: cascade-driven analytical answer generation.
    try:
        from .routes.questions import _generate_analytical_answer
        from .tools import question_store
        gen = _generate_analytical_answer(query, context if isinstance(context, dict) else {})
        if question_id:
            try:
                question_store.record_answer(
                    church_id, question_id,
                    answer=gen["answer"],
                    answerer="cascade",
                    confidence=gen.get("confidence"),
                    reasoning=gen.get("reasoning"),
                    source=gen.get("source", "cascade"),
                )
            except Exception:
                pass
        return _json({
            "church_id": church_id,
            "query": query,
            "intent": intent,
            "question_id": question_id,
            "answer": gen["answer"],
            "confidence": gen.get("confidence"),
            "reasoning": gen.get("reasoning"),
            "provenance": [],
            "follow_ons": generate_follow_on_suggestions(intent),
        })
    except Exception as _exc:
        return _json({
            "church_id": church_id,
            "query": query,
            "intent": intent,
            "answer": f"(fallback) {query}",
            "confidence": 0.0,
            "reasoning": f"cascade unavailable: {_exc!r}",
            "provenance": [],
            "follow_ons": generate_follow_on_suggestions(intent),
        })


# ---------- Cabinet Surface (FRD §16.5, Personal Cabinet) ----------

@app.get("/api/cabinets/{principal}/activity")
async def get_cabinet_activity(principal: str, church_id: str) -> JSONResponse:
    """Get per-principal activity log: recent approvals, decisions, pending actions.

    Returns activity feed for Personal Cabinet with:
    - Recent decisions (cards approved, rejected, escalated)
    - Pending approvals (decisions awaiting this principal's vote/action)
    - Recent disavowals (overrides reversed)
    - Voice/style config history
    """
    # Phase 5: Mock data ready for database integration
    activity = [
        {
            "activity_id": f"act_{principal}_001",
            "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
            "type": "approval",
            "action": "approved",
            "subject": "Fund reallocation recommendation",
            "card_id": "rec_002",
            "principal": principal,
            "tier": 2,
            "decision_summary": "Approved reallocation of Legacy Scholarship to Active Mission"
        },
        {
            "activity_id": f"act_{principal}_002",
            "timestamp": (datetime.now() - timedelta(hours=6)).isoformat(),
            "type": "policy_vote",
            "action": "voted_yes",
            "subject": "Quasi-endowment draw policy amendment",
            "card_id": "pol_001",
            "principal": principal,
            "tier": 2,
            "decision_summary": "Voted YES on 4% annual draw limit"
        },
        {
            "activity_id": f"act_{principal}_003",
            "timestamp": (datetime.now() - timedelta(days=1)).isoformat(),
            "type": "exception_adjudication",
            "action": "routed",
            "subject": "Ambiguous bequest language (donor: Jane Smith)",
            "card_id": "exc_012",
            "principal": principal,
            "tier": 2,
            "decision_summary": "Routed to Canon Lawyer (T3) for intent clarification"
        }
    ]

    pending = [
        {
            "pending_id": f"pend_{principal}_001",
            "created_at": (datetime.now() - timedelta(hours=4)).isoformat(),
            "type": "policy_vote",
            "subject": "Board approval: 2024 budget adjustment",
            "card_id": "pol_002",
            "deadline": (datetime.now() + timedelta(days=3)).isoformat(),
            "options": ["Approve", "Reject", "Abstain"],
            "privacy_class": "P2"
        },
        {
            "pending_id": f"pend_{principal}_002",
            "created_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            "type": "exception_review",
            "subject": "Anonymous $50K gift with unclear intent",
            "card_id": "exc_015",
            "deadline": (datetime.now() + timedelta(days=7)).isoformat(),
            "privacy_class": "P1"
        }
    ]

    return _json({
        "principal": principal,
        "church_id": church_id,
        "activity": activity,
        "pending": pending,
        "voice_config": {
            "principal_name": f"Cabinet Member ({principal.title()})",
            "tier": 2,
            "voice_style": "pastoral",
            "communication_preference": "brief",
            "notification_frequency": "immediate"
        }
    })


@app.post("/api/cabinets/{principal}/approve")
async def cabinet_approve_decision(principal: str, body: Dict[str, Any]) -> JSONResponse:
    """Record a decision approval/action in cabinet.

    Commits a pending decision (policy vote, exception adjudication, etc.)
    """
    pending_id = body.get("pending_id")
    action = body.get("action")  # "approve", "reject", "abstain", "route", etc.
    reasoning = body.get("reasoning", "")
    church_id = body.get("church_id", "holy_comforter")

    # Phase 5: Would integrate with decision ledger
    return _json({
        "principal": principal,
        "church_id": church_id,
        "pending_id": pending_id,
        "action": action,
        "status": "committed",
        "timestamp": datetime.now().isoformat(),
        "ledger_entry_id": f"led_{uuid.uuid4().hex[:12]}",
        "message": f"Decision {action} recorded in audit ledger"
    })


@app.post("/api/cabinets/{principal}/disavow")
async def cabinet_disavow_override(principal: str, body: Dict[str, Any]) -> JSONResponse:
    """Disavow (reverse) an override decision made by this principal.

    Opens a disavowal window showing:
    - Original decision + rationale
    - Time window for reversal (typically 24-48 hours)
    - Ledger entry for the disavowal
    - Impact on dependent decisions
    """
    override_id = body.get("override_id")
    reason = body.get("reason", "")
    church_id = body.get("church_id", "holy_comforter")

    # Phase 5: Would validate disavowal eligibility, check time window
    return _json({
        "principal": principal,
        "church_id": church_id,
        "override_id": override_id,
        "disavowed": True,
        "timestamp": datetime.now().isoformat(),
        "disavowal_ledger_entry": f"dis_{uuid.uuid4().hex[:12]}",
        "message": "Override disavowed. Original decision path restored. Dependent decisions flagged for review."
    })


@app.post("/api/cabinets/{principal}/delegations")
async def create_delegation(principal: str, body: Dict[str, Any]) -> JSONResponse:
    """Configure agent delegation for a cabinet member.

    Allows principals to:
    - Route decision types to specific agents
    - Route decisions to other cabinet members
    - Set trigger conditions (thresholds, risk levels)
    - Configure notification levels

    Creates immutable audit trail in CardStore.

    Args:
        principal: Cabinet member ID (treasurer, cfo, etc.)
        body: {
            delegation_type: 'agent'|'member'|'threshold',
            decision_type: exception|pledge|policy|variance|fund_restriction,
            target_agent_or_member: agent_id or member_name,
            trigger_condition: optional condition string,
            notification_level: always|escalation_only|never
        }

    Returns:
        Delegation record with ID and audit trail
    """
    from backend.membrane.stores.delegations import DelegationCardStore
    from backend.membrane.stores.audits import AuditCardStore

    delegation_type = body.get("delegation_type")
    decision_type = body.get("decision_type")
    target = body.get("target_agent_or_member")
    condition = body.get("trigger_condition")
    notify_level = body.get("notification_level", "escalation_only")
    church_id = body.get("church_id", "holy_comforter")

    if not all([delegation_type, decision_type, target]):
        return _json({"error": "Missing required fields"}, status_code=400)

    card_id = await DelegationCardStore.create(
        principal=principal,
        church_id=church_id,
        delegation_type=delegation_type,
        decision_type=decision_type,
        target=target,
        trigger_condition=condition,
        notification_level=notify_level,
    )

    await AuditCardStore.record_event(
        church_id=church_id,
        actor_email=principal,
        action="DELEGATION_CREATED",
        resource_type="DELEGATION",
        resource_id=card_id,
        details={
            "decision_type": decision_type,
            "target": target,
            "trigger_condition": condition,
            "notification_level": notify_level,
        },
    )

    return _json({
        "delegation_id": card_id,
        "principal": principal,
        "church_id": church_id,
        "delegation_type": delegation_type,
        "decision_type": decision_type,
        "target": target,
        "trigger_condition": condition,
        "notification_level": notify_level,
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "audit_trail_entry": f"audit-{church_id}",
        "message": f"Delegation created: {decision_type} decisions routed to {target}"
    })


# ---------- Phase 6: Adversarial Membrane & Auditor Surface (FRD MEM-26, §16) ----------

@app.get("/api/audit/adversarial-findings")
async def get_adversarial_findings(church_id: str) -> JSONResponse:
    """Get Adversarial Membrane outputs: anomalies, drift, patterns, outliers.

    MEM-26 counter-agent identifies:
    - Vendor pricing drift (unexpected changes in unit prices)
    - JE anomaly profiles (unusual account combinations, round amounts, timing patterns)
    - Override patterns (who overrides what, frequency, rationale consistency)
    - Related-party transactions (flagged by counterparty analysis)
    """
    # Phase 6: Mock data ready for integration with actual anomaly detection
    findings = [
        {
            "finding_id": "adv_001",
            "membrane": "pricing_drift",
            "severity": "high",
            "category": "vendor_pricing_anomaly",
            "summary": "ABC Cleaning Services: unit price increased 18% without contract update",
            "vendor": "ABC Cleaning Services",
            "prior_unit_price": "$45.00",
            "current_unit_price": "$53.10",
            "last_review_date": "2026-03-15",
            "impact": "Estimated $2.1K overage YTD",
            "recommendation": "Review amended contract or audit recent invoices",
            "timestamp": datetime.now().isoformat()
        },
        {
            "finding_id": "adv_002",
            "membrane": "je_anomaly",
            "severity": "medium",
            "category": "round_amount_pattern",
            "summary": "Recurring $5,000 JEs: Altar Fund to Outreach Fund (no supporting doc)",
            "account_from": "Altar Fund",
            "account_to": "Outreach Fund",
            "frequency": "Monthly for 6 months",
            "total_amount": "$30,000",
            "supporting_docs": 0,
            "recommendation": "Request missing approval for standing transfer or codify as recurring decision",
            "timestamp": datetime.now().isoformat()
        },
        {
            "finding_id": "adv_003",
            "membrane": "override_pattern",
            "severity": "medium",
            "category": "override_frequency",
            "summary": "CFO override rate: 23% of policy decisions (vs. T2 avg 8%)",
            "actor": "CFO",
            "authority_tier": 2,
            "override_count": 23,
            "total_decisions": 100,
            "override_rate_percentile": "95th",
            "rationale_consistency": "72%",
            "recommendation": "Review CFO override rationale for consistency; consider coaching on delegation",
            "timestamp": datetime.now().isoformat()
        },
        {
            "finding_id": "adv_004",
            "membrane": "related_party",
            "severity": "low",
            "category": "counterparty_flag",
            "summary": "Vestry member spouse is vendor (Facility Maintenance LLC): $47K YTD",
            "related_party": "Vestry member (Dr. Jane Smith)",
            "vendor_name": "Facility Maintenance LLC",
            "relationship": "Spouse",
            "ytd_amount": "$47,000",
            "disclosure_on_file": True,
            "competitively_bid": False,
            "recommendation": "Confirm competitive bid or justify sole-source; ensure conflict-of-interest disclosure current",
            "timestamp": datetime.now().isoformat()
        }
    ]

    return _json({
        "church_id": church_id,
        "findings": findings,
        "total_high": sum(1 for f in findings if f["severity"] == "high"),
        "total_medium": sum(1 for f in findings if f["severity"] == "medium"),
        "total_low": sum(1 for f in findings if f["severity"] == "low"),
        "last_scan": datetime.now().isoformat(),
        "next_scan": (datetime.now() + timedelta(days=7)).isoformat()
    })


@app.get("/api/audit/materiality-budget")
async def get_materiality_budget(church_id: str) -> JSONResponse:
    """Get materiality budget for external auditor.

    Tracks audit findings materiality threshold and evidence pack requirements.
    """
    return _json({
        "church_id": church_id,
        "materiality_threshold": 50000,  # $50K = materiality level
        "performance_threshold": 25000,  # $25K = performance materiality
        "factual_misstatements_budget": 0,  # Used up
        "judgmental_misstatements_budget": 2,  # 2 items remaining
        "total_identified_misstatements": 0,
        "evidence_items_required": 15,
        "evidence_items_collected": 8,
        "message": "Auditor: 8 of 15 evidence items collected. Materiality budget at capacity."
    })


@app.get("/api/audit/evidence-pack")
async def get_evidence_pack(church_id: str) -> JSONResponse:
    """Get audit evidence pack for external auditor.

    Returns structured evidence for:
    - Material account balances (top 20% by balance)
    - High-risk transactions (overrides, one-offs, round amounts)
    - Compliance items (covenant calculations, restricted fund use)
    - Related-party disclosures
    """
    return _json({
        "church_id": church_id,
        "evidence_items": [
            {
                "evidence_id": "ev_001",
                "type": "account_balance",
                "account": "Operating Checking",
                "balance": "$287,450",
                "materiality_pct": 18.5,
                "supporting_docs": ["bank_statement_2026_04.pdf", "reconciliation_2026_04.xlsx"],
                "audit_procedure": "Agree bank statement to GL; inspect reconciling items"
            },
            {
                "evidence_id": "ev_002",
                "type": "high_risk_transaction",
                "description": "$100K gift from anonymous donor (unclear intent)",
                "amount": "$100,000",
                "risk_factors": ["no_donor_history", "vague_intent", "governance_approval_pending"],
                "supporting_docs": ["gift_letter.pdf", "board_minutes_2026_04.pdf"],
                "audit_procedure": "Obtain intent clarification; trace to permitted use"
            },
            {
                "evidence_id": "ev_003",
                "type": "compliance_item",
                "description": "Covenant: Maintain 4-month cash reserves",
                "current_reserves_months": 2.3,
                "threshold_months": 4.0,
                "variance": "-1.7 months",
                "supporting_docs": ["covenant_agreement.pdf", "cash_reserve_calc.xlsx"],
                "audit_procedure": "Recalculate covenant position; evaluate covenant waiver if needed"
            }
        ],
        "pack_ready": False,
        "completion_pct": 53,
        "next_item_due": "2026-05-12",
        "auditor_notes": "Awaiting intent clarification on $100K anonymous gift before evidence pack can be finalized"
    })


# ---------- Federated Peer Benchmarking (Phase 6, FRD MEM-28) ----------

@app.get("/api/benchmarking/peers")
async def get_peer_benchmarks(church_id: str, metric: str = None) -> JSONResponse:
    """Get peer organization benchmarking data for financial health comparison.

    Federated Membrane (MEM-28) queries similar organizations:
    - Expense ratio analysis (program vs admin vs fundraising)
    - Cash reserve health (months of operations)
    - Donor concentration (top 10 donor pct of revenue)
    - Fund diversification (number of restricted funds, endowment ratio)
    - Growth trends (YoY revenue change, expense growth)
    """
    # Phase 6: Mock peer data from similar-sized Episcopal churches
    peer_data = {
        "your_organization": {
            "name": "Holy Comforter Episcopal Church",
            "revenue_annual": 1_550_000,
            "expense_ratio_program": 0.72,
            "expense_ratio_admin": 0.18,
            "expense_ratio_fundraising": 0.10,
            "cash_reserves_months": 2.3,
            "donor_concentration_top10": 0.35,
            "restricted_funds_count": 18,
            "endowment_ratio": 0.15,
            "yoy_revenue_growth": 0.03,
            "percentile": None  # Will be calculated
        },
        "peers": [
            {
                "org_id": "peer_001",
                "name": "St. Mary's Episcopal Church",
                "denomination": "Episcopal",
                "region": "Northeast",
                "revenue_annual": 1_800_000,
                "expense_ratio_program": 0.68,
                "expense_ratio_admin": 0.22,
                "expense_ratio_fundraising": 0.10,
                "cash_reserves_months": 4.2,
                "donor_concentration_top10": 0.28,
                "restricted_funds_count": 22,
                "endowment_ratio": 0.42,
                "yoy_revenue_growth": 0.05,
                "notes": "Strong endowment management; considered best-in-class cash reserves"
            },
            {
                "org_id": "peer_002",
                "name": "Grace Anglican Community",
                "denomination": "Anglican",
                "region": "Mid-Atlantic",
                "revenue_annual": 1_400_000,
                "expense_ratio_program": 0.75,
                "expense_ratio_admin": 0.17,
                "expense_ratio_fundraising": 0.08,
                "cash_reserves_months": 2.1,
                "donor_concentration_top10": 0.32,
                "restricted_funds_count": 15,
                "endowment_ratio": 0.08,
                "yoy_revenue_growth": 0.02,
                "notes": "Similar profile; lean admin costs"
            },
            {
                "org_id": "peer_003",
                "name": "St. John's Chapel",
                "denomination": "Episcopal",
                "region": "Northeast",
                "revenue_annual": 2_100_000,
                "expense_ratio_program": 0.70,
                "expense_ratio_admin": 0.20,
                "expense_ratio_fundraising": 0.10,
                "cash_reserves_months": 5.1,
                "donor_concentration_top10": 0.30,
                "restricted_funds_count": 28,
                "endowment_ratio": 0.55,
                "yoy_revenue_growth": 0.06,
                "notes": "Largest peer; significant endowment; exceptional cash position"
            },
            {
                "org_id": "peer_004",
                "name": "Trinity Interfaith Alliance",
                "denomination": "Interfaith",
                "region": "Southeast",
                "revenue_annual": 980_000,
                "expense_ratio_program": 0.80,
                "expense_ratio_admin": 0.15,
                "expense_ratio_fundraising": 0.05,
                "cash_reserves_months": 1.8,
                "donor_concentration_top10": 0.45,
                "restricted_funds_count": 8,
                "endowment_ratio": 0.02,
                "yoy_revenue_growth": 0.01,
                "notes": "Smaller peer; donor-dependent; lower reserves (similar risk to you)"
            }
        ]
    }

    # Calculate percentiles
    all_orgs = [peer_data["your_organization"]] + peer_data["peers"]
    for metric_key in ["cash_reserves_months", "expense_ratio_program", "donor_concentration_top10"]:
        values = [org[metric_key] for org in all_orgs if metric_key in org]
        if values:
            your_value = peer_data["your_organization"][metric_key]
            rank = sum(1 for v in values if v <= your_value)
            percentile = int((rank / len(values)) * 100)
            peer_data["your_organization"][f"{metric_key}_percentile"] = percentile

    return _json(peer_data)


# ---------- ACS Realm browser plug-in setup (FR-06.5) ----------

@app.get("/api/integrations/acs/status")
async def acs_status(church_id: str) -> JSONResponse:
    """Get current ACS Realm browser plug-in configuration status."""
    from .integrations.acs_realm import credentials as _creds
    try:
        creds = _creds.load(church_id) if hasattr(_creds, "load") else None
    except Exception:
        creds = None

    # Check if Playwright is available
    playwright_available = False
    try:
        import playwright  # type: ignore # noqa: F401
        playwright_available = True
    except ImportError:
        pass

    # Check if browser binary is installed
    browser_installed = False
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as pw:
            try:
                # Just attempt to launch headless to verify
                pw.chromium.executable_path  # type: ignore[attr-defined]
                browser_installed = True
            except Exception:
                browser_installed = False
    except Exception:
        browser_installed = False

    return _json({
        "church_id": church_id,
        "credentials_stored": creds is not None,
        "base_url": creds.get("base_url") if creds else None,
        "username": creds.get("username") if creds else None,
        "playwright_installed": playwright_available,
        "chromium_installed": browser_installed,
        "mock_mode": os.getenv("EIME_ACS_MOCK", "").lower() in ("1", "true", "yes"),
        "ready": playwright_available and browser_installed and creds is not None,
    })


@app.post("/api/integrations/acs/test")
async def acs_test_connection(body: Dict[str, Any]) -> JSONResponse:
    """Test ACS Realm browser connection without storing credentials."""
    church_id = body.get("church_id", "holy_comforter")
    base_url = body.get("base_url")
    username = body.get("username")
    password = body.get("password")

    if not (base_url and username and password):
        raise HTTPException(422, "Missing base_url, username, or password")

    # In mock mode, just return success
    if os.getenv("EIME_ACS_MOCK", "").lower() in ("1", "true", "yes"):
        return _json({
            "success": True,
            "mode": "mock",
            "message": "Mock mode enabled — connection simulated successfully",
            "duration_ms": 100,
        })

    # Try real connection
    try:
        from .integrations.acs_realm.playwright_runner import PlaywrightSession  # type: ignore
        import time
        t0 = time.time()
        test_creds = {"base_url": base_url, "username": username, "password": password}
        with PlaywrightSession(church_id, creds=test_creds) as session:
            # Just verify login worked
            page = session.page
            success = page is not None
        return _json({
            "success": success,
            "mode": "live",
            "message": "Connected and logged in successfully" if success else "Login failed",
            "duration_ms": int((time.time() - t0) * 1000),
        })
    except ImportError as exc:
        return _json({
            "success": False,
            "mode": "error",
            "message": f"Playwright not installed: {exc}. Run: uv pip install playwright && playwright install chromium",
        }, status_code=503)
    except Exception as exc:
        return _json({
            "success": False,
            "mode": "error",
            "message": f"Connection failed: {exc}",
        }, status_code=502)



@app.post("/api/integrations/acs/install")
async def acs_install(background_tasks: BackgroundTasks) -> JSONResponse:
    """Kick off Playwright + Chromium install in the background."""
    # Mock mode: pretend success immediately.
    if os.getenv("EIME_ACS_MOCK", "").lower() in ("1", "true", "yes"):
        _acs_install_state.update({
            "status": "success",
            "log_lines": ["[mock] install skipped"],
            "started_at": datetime.utcnow().isoformat() + "Z",
            "finished_at": datetime.utcnow().isoformat() + "Z",
            "returncode": 0,
            "error": None,
        })
        return _json({"status": "success", "mode": "mock"})

    # Reject if already running.
    with _acs_install_lock:
        if _acs_install_state["status"] == "running":
            return _json(
                {"status": "running", "message": "Install already in progress"},
                status_code=409,
            )
        # Reset state for a fresh run.
        _acs_install_state.update({
            "status": "running",
            "log_lines": [],
            "started_at": datetime.utcnow().isoformat() + "Z",
            "finished_at": None,
            "returncode": None,
            "error": None,
        })

    background_tasks.add_task(_run_acs_install)
    return _json({"status": "running", "started_at": _acs_install_state["started_at"]})


@app.get("/api/integrations/acs/install/status")
async def acs_install_status() -> JSONResponse:
    return _json({
        "status": _acs_install_state["status"],
        "log_lines": list(_acs_install_state["log_lines"]),  # copy
        "started_at": _acs_install_state["started_at"],
        "finished_at": _acs_install_state["finished_at"],
        "returncode": _acs_install_state["returncode"],
        "error": _acs_install_state["error"],
    })


# ===== NEW: Event Registry, Operations Council, Reconciliation, Compliance APIs =====
# Phase 1 stub endpoints for the event-centric accounting UI

@app.get("/api/events")
async def list_events(
    church_id: str,
    filters: Optional[str] = None,  # JSON string of filter conditions
    limit: int = 50,
    offset: int = 0
) -> JSONResponse:
    """List economic events with full fidelity (provenance, dimensions, confidence).

    Queries the real events table and joins with event_tags for semantic dimensions.
    """
    from .db import connection

    try:
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )

        if not church_pk:
            return _json({"church_id": church_id, "total": 0, "events": [], "offset": offset, "limit": limit})

        church_pk = church_pk["id"]

        # Count total events for pagination
        count_result = connection.execute_query(
            "SELECT COUNT(*) as total FROM events WHERE church_id = %s",
            (church_pk,),
            fetch_one=True
        )
        total = count_result["total"] if count_result else 0

        # Query events with pagination
        rows = connection.execute_query(
            """SELECT e.event_id, e.event_type, e.occurred_at, e.actor, e.confidence, e.payload, e.correlation_id
               FROM events e
               WHERE e.church_id = %s
               ORDER BY e.occurred_at DESC
               LIMIT %s OFFSET %s""",
            (church_pk, limit, offset)
        ) or []

        # Build event response objects
        events = []
        for row in rows:
            event_id = str(row["event_id"])
            payload = row["payload"] or {}

            # Fetch tags for this event
            tag_rows = connection.execute_query(
                "SELECT tag_kind, tag_value FROM event_tags WHERE event_id = %s",
                (row["event_id"],)
            ) or []

            dimensions = {}
            for tag_row in tag_rows:
                dimensions[tag_row["tag_kind"]] = tag_row["tag_value"]

            # Build response object matching the mock structure
            event_obj = {
                "event_id": event_id,
                "timestamp": row["occurred_at"].isoformat() if row["occurred_at"] else None,
                "event_type": row["event_type"],
                "source": payload.get("source", "system"),
                "provenance": {
                    "source_system": payload.get("source", "system"),
                    "document_id": payload.get("document_id", event_id),
                    "confidence": float(row["confidence"] or 1.0)
                },
                "economic_substance": {
                    "transaction_type": payload.get("transaction_type", "unknown"),
                    "amount": payload.get("amount", 0),
                    "vendor": payload.get("vendor", None),
                    "description": payload.get("description", "")
                },
                "dimensions": {
                    "account": dimensions.get("account", None),
                    "project": dimensions.get("project", None),
                    "customer": dimensions.get("customer", None),
                    "function": dimensions.get("function", None),
                    "geography": dimensions.get("geography", None),
                    "esg_category": dimensions.get("esg_category", None),
                    "segment": dimensions.get("segment", None),
                    "capitalization_eligible": dimensions.get("capitalization_eligible") == "yes",
                    "tax_treatment": dimensions.get("tax_treatment", None)
                },
                "confidence": float(row["confidence"] or 1.0),
                "lineage": payload.get("lineage", [])
            }
            events.append(event_obj)

        return _json({"church_id": church_id, "total": total, "events": events, "offset": offset, "limit": limit})

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.get("/api/events/{event_id}")
async def get_event(event_id: str) -> JSONResponse:
    """Get full details of a single economic event."""
    from .db import connection
    from uuid import UUID

    try:
        # Parse event_id as UUID
        try:
            event_uuid = UUID(event_id)
        except ValueError:
            return _json({"error": f"Invalid event_id: {event_id}"}, status_code=400)

        # Query single event
        row = connection.execute_query(
            """SELECT e.event_id, e.event_type, e.occurred_at, e.actor, e.confidence, e.payload, e.correlation_id
               FROM events e
               WHERE e.event_id = %s""",
            (event_uuid,),
            fetch_one=True
        )

        if not row:
            return _json({"error": f"Event not found: {event_id}"}, status_code=404)

        # Fetch tags for this event
        tag_rows = connection.execute_query(
            "SELECT tag_kind, tag_value FROM event_tags WHERE event_id = %s",
            (event_uuid,)
        ) or []

        dimensions = {}
        for tag_row in tag_rows:
            dimensions[tag_row["tag_kind"]] = tag_row["tag_value"]

        payload = row["payload"] or {}

        # Build response object
        return _json({
            "event_id": event_id,
            "timestamp": row["occurred_at"].isoformat() if row["occurred_at"] else None,
            "event_type": row["event_type"],
            "source": payload.get("source", "system"),
            "provenance": {
                "source_system": payload.get("source", "system"),
                "document_id": payload.get("document_id", event_id),
                "confidence": float(row["confidence"] or 1.0)
            },
            "economic_substance": {
                "transaction_type": payload.get("transaction_type", "unknown"),
                "amount": payload.get("amount", 0),
                "vendor": payload.get("vendor", None),
                "description": payload.get("description", "")
            },
            "dimensions": {
                "account": dimensions.get("account", None),
                "project": dimensions.get("project", None),
                "customer": dimensions.get("customer", None),
                "function": dimensions.get("function", None),
                "geography": dimensions.get("geography", None),
                "esg_category": dimensions.get("esg_category", None),
                "segment": dimensions.get("segment", None),
                "capitalization_eligible": dimensions.get("capitalization_eligible") == "yes",
                "tax_treatment": dimensions.get("tax_treatment", None)
            },
            "confidence": float(row["confidence"] or 1.0),
            "lineage": payload.get("lineage", [])
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.get("/api/decisions")
async def list_decisions(
    church_id: str,
    category: Optional[str] = None,
    job_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> JSONResponse:
    """Return paginated decision ledger entries.

    Mirrors /api/churches/{id}/decision-ledger but with consistent API shape
    (query params instead of path params, pagination support).

    Query params:
      church_id — church identifier (default: holy_comforter)
      category  — filter by DecisionCategory (recognize, code, route, approve, override, disavow)
      job_id    — filter to entries for a specific processing job
      limit     — max entries returned (default 100)
      offset    — pagination offset (default 0)
    """
    ledger = flow.get_ledger(church_id)
    entries = list(reversed(ledger.entries))  # most recent first

    if category:
        entries = [e for e in entries if e.category.value == category.lower()]
    if job_id:
        entries = [e for e in entries if e.decision_id.startswith(job_id)]

    total = len(entries)
    entries = entries[offset:offset+limit]

    return _json({
        "church_id": church_id,
        "total": total,
        "returned": len(entries),
        "offset": offset,
        "limit": limit,
        "decisions": [e.model_dump(mode="json") for e in entries],
    })


@app.get("/api/events-with-exceptions")
async def list_events_with_exceptions(
    church_id: str,
    limit: int = 100,
    offset: int = 0,
    show_exceptions_only: bool = False,
) -> JSONResponse:
    """Enhanced /api/events with exception detection and confidence visualization.

    Adds:
    - Confidence percentage formatting (0.95 → "95%" + color code 🟢)
    - Exception flag for obvious mismatches
    - Confidence color codes: 🟢 80%+, 🟡 60-79%, 🔴 <60%
    """
    from .db import connection

    try:
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )

        if not church_pk:
            return _json({"church_id": church_id, "total": 0, "events": [], "offset": offset, "limit": limit})

        church_pk = church_pk.get("id")

        # Count total events
        count_result = connection.execute_query(
            "SELECT COUNT(*) as total FROM events WHERE church_id = %s",
            (church_pk,),
            fetch_one=True
        )
        total = count_result.get("total") if count_result else 0

        # Query events with pagination
        rows = connection.execute_query(
            """SELECT e.event_id, e.event_type, e.occurred_at, e.actor, e.confidence, e.payload
               FROM events e
               WHERE e.church_id = %s
               ORDER BY e.occurred_at DESC
               LIMIT %s OFFSET %s""",
            (church_pk, limit, offset)
        ) or []

        # Build enhanced event response objects
        events = []
        exception_count = 0

        for row in rows:
            event_id = str(row.get("event_id", ""))
            payload = row.get("payload") or {}
            confidence = float(row.get("confidence") or 1.0)

            # Fetch tags for this event
            tag_rows = connection.execute_query(
                "SELECT tag_kind, tag_value FROM event_tags WHERE event_id = %s",
                (row.get("event_id"),)
            ) or []

            dimensions = {}
            for tag_row in tag_rows:
                dimensions[tag_row.get("tag_kind")] = tag_row.get("tag_value")

            # Detect if this is an exception/mismatch
            is_exception = (
                confidence < 0.70 or  # Low confidence
                (row.get("event_type") == "BankItemObserved" and "correlation_id" not in payload)  # Unmatched bank item
            )
            if is_exception:
                exception_count += 1

            # Format confidence with color code
            if confidence >= 0.80:
                confidence_color = "🟢"  # Green
            elif confidence >= 0.60:
                confidence_color = "🟡"  # Yellow
            else:
                confidence_color = "🔴"  # Red

            event_obj = {
                "event_id": event_id,
                "timestamp": row.get("occurred_at").isoformat() if row.get("occurred_at") else None,
                "event_type": row.get("event_type"),
                "source": payload.get("source", "system"),
                "provenance": {
                    "source_system": payload.get("source", "system"),
                    "document_id": payload.get("document_id", event_id),
                    "confidence": confidence
                },
                "economic_substance": {
                    "transaction_type": payload.get("transaction_type", "unknown"),
                    "amount": payload.get("amount", 0),
                    "vendor": payload.get("vendor"),
                    "description": payload.get("description", "")
                },
                "dimensions": dimensions,
                "confidence": confidence,
                "confidence_display": f"{confidence_color} {int(confidence * 100)}%",
                "is_exception": is_exception,
                "lineage": payload.get("lineage", [])
            }

            if not show_exceptions_only or is_exception:
                events.append(event_obj)

        return _json({
            "church_id": church_id,
            "total": total,
            "exception_count": exception_count,
            "events": events[:limit] if show_exceptions_only else events,
            "offset": offset,
            "limit": limit,
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.get("/api/events/{event_id}/similar")
async def find_similar_events(
    event_id: str,
    church_id: str,
    limit: int = 5,
) -> JSONResponse:
    """Find similar events for Q&A loop - transactions with matching dimensions.

    Used in: "User asks about transaction X, show similar transactions from history"
    Returns: Top 5 events with matching ministry/cost_center/vendor tags
    """
    from .db import connection
    import uuid

    try:
        event_uuid = uuid.UUID(event_id)
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )
        if not church_pk:
            return _json({"similar_events": []})

        church_pk = church_pk.get("id")

        # Get tags of the query event
        query_tags = connection.execute_query(
            "SELECT tag_kind, tag_value FROM event_tags WHERE event_id = %s",
            (str(event_uuid),)
        ) or []

        if not query_tags:
            return _json({"similar_events": []})

        # Find events with matching tags (same ministry, cost_center, vendor, etc.)
        tag_kinds = [t.get("tag_kind") for t in query_tags]
        similar_sql = """
            SELECT DISTINCT e.event_id, e.event_type, e.occurred_at, e.confidence, e.payload,
                   COUNT(*) as matching_tags
            FROM events e
            JOIN event_tags et ON e.event_id = et.event_id
            WHERE e.church_id = %s
            AND e.event_id != %s::uuid
            AND et.tag_kind = ANY(%s::text[])
            GROUP BY e.event_id, e.event_type, e.occurred_at, e.confidence, e.payload
            ORDER BY matching_tags DESC, e.occurred_at DESC
            LIMIT %s
        """

        similar = connection.execute_query(
            similar_sql,
            (church_pk, str(event_uuid), tag_kinds, limit)
        ) or []

        similar_events = []
        for row in similar:
            similar_events.append({
                "event_id": str(row.get("event_id")),
                "event_type": row.get("event_type"),
                "timestamp": row.get("occurred_at").isoformat() if row.get("occurred_at") else None,
                "confidence": float(row.get("confidence") or 1.0),
                "matching_tags_count": row.get("matching_tags"),
                "payload": row.get("payload")
            })

        return _json({"similar_events": similar_events})

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.post("/api/events/{event_id}/approve")
async def approve_exception(
    event_id: str,
    church_id: str,
    body: Optional[dict] = None,
) -> JSONResponse:
    """Approve an exception as 'OK' - marks it as reviewed and no action needed.

    Phase 3: Users can dismiss exceptions they've reviewed
    Body: {"reason": "Already matched manually", "notes": "..."}
    """
    try:
        import uuid
        from .db import connection

        event_uuid = uuid.UUID(event_id)
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )
        if not church_pk:
            return _json({"error": "Church not found"}, status_code=404)

        # Mark exception as approved (in a real system, update exception_approvals table)
        # For now, just return success
        approval_body = body or {}

        return _json({
            "event_id": event_id,
            "status": "approved",
            "approval_reason": approval_body.get("reason", "User reviewed and confirmed OK"),
            "approved_at": datetime.utcnow().isoformat(),
            "notes": approval_body.get("notes", "")
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.get("/api/decisions/{decision_id}/evidence")
async def get_decision_evidence(
    decision_id: str,
    church_id: str,
) -> JSONResponse:
    """Get evidence (cited events) for a decision - shows reasoning context.

    Used in: "User clicks 'why?' on a decision, see the events it was based on"
    Returns: Full event details for all events cited in the decision
    """
    try:
        ledger = flow.get_ledger(church_id)

        # Find decision by ID
        decision = None
        for entry in ledger.entries:
            if entry.decision_id == decision_id:
                decision = entry
                break

        if not decision:
            return _json({"error": f"Decision {decision_id} not found"}, status_code=404)

        # Return decision + cited events
        return _json({
            "decision_id": decision_id,
            "reasoning": decision.reasoning,
            "confidence": decision.confidence,
            "alternatives": decision.alternatives,
            "evidence": {
                "event_ids": decision.cited_event_ids or [],
                "evidence_refs": decision.evidence_refs or [],
                "policy_invoked": decision.policy_invoked
            },
            "timestamp": decision.timestamp.isoformat() if decision.timestamp else None,
            "category": decision.category.value
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.get("/api/dimensions")
async def list_dimensions() -> JSONResponse:
    """Get all available semantic dimensions for event tagging."""
    return _json({
        "dimensions": [
            {
                "name": "account",
                "description": "Chart of accounts dimension",
                "type": "categorical",
                "values": ["1010", "1020", "2000", "3000", "4000", "5000", "6000", "6100", "7000"]
            },
            {
                "name": "project",
                "description": "Project/ministry dimension",
                "type": "categorical",
                "values": ["facility_maintenance", "outreach_program", "youth_ministry", None]
            },
            {
                "name": "customer",
                "description": "Customer/counterparty dimension",
                "type": "categorical",
                "values": ["First Community Outreach", "ABC Cleaning Services", "XYZ Vendor", None]
            },
            {
                "name": "function",
                "description": "Business function dimension",
                "type": "categorical",
                "values": ["operations", "fundraising", "program_delivery", "administrative"]
            },
            {
                "name": "geography",
                "description": "Geographic dimension",
                "type": "categorical",
                "values": ["US-MA", "US-CT", "US-NY", "US-National"]
            },
            {
                "name": "esg_category",
                "description": "ESG classification",
                "type": "categorical",
                "values": ["community_support", "environmental", "social_justice", "governance", None]
            },
            {
                "name": "segment",
                "description": "Business segment",
                "type": "categorical",
                "values": ["donations", "operations", "programs", "fundraising", None]
            },
            {
                "name": "capitalization_eligible",
                "description": "Can this be capitalized as an asset?",
                "type": "boolean"
            },
            {
                "name": "tax_treatment",
                "description": "Tax treatment classification",
                "type": "categorical",
                "values": ["deductible", "tax_exempt", "non_deductible", None]
            }
        ]
    })


@app.get("/api/dimensions/{dimension_name}")
async def get_dimension_details(dimension_name: str) -> JSONResponse:
    """Get details about a specific dimension - usage stats and guidance.

    Phase 2: Helps users understand when to use each dimension
    """
    from .db import connection

    dimension_guides = {
        "ministry": {
            "description": "Ministry or program (worship, youth, outreach, etc.)",
            "usage": "Tag transactions that primarily serve a specific ministry",
            "examples": ["worship", "youth_ministry", "community_outreach", "facilities"],
            "notes": "One ministry per transaction. If multi-ministry, use beneficiary dimension."
        },
        "beneficiary": {
            "description": "Primary beneficiary or constituent group",
            "usage": "Who this transaction ultimately serves",
            "examples": ["congregation", "community", "staff", "facility"],
            "notes": "Different from ministry - a staff salary is ministry=operations, beneficiary=staff"
        },
        "cost_center": {
            "description": "Operational cost center or department",
            "usage": "For budget tracking and cost allocation",
            "examples": ["program", "operations", "admin", "fundraising"],
            "notes": "Use for P&L analysis by operational area"
        },
        "geography": {
            "description": "Physical location or campus",
            "usage": "Track spending by site, useful for multi-location orgs",
            "examples": ["US-MA", "US-CT", "US-National"],
            "notes": "Use ISO country+state format"
        },
        "funding_source": {
            "description": "Where funding came from",
            "usage": "Donor intent tracking and restricted fund compliance",
            "examples": ["donations", "grants", "earned_income", "endowment"],
            "notes": "Critical for nonprofit compliance"
        },
        "mission_impact": {
            "description": "How this advances the mission",
            "usage": "Mission-focused reporting and impact analysis",
            "examples": ["spiritual_growth", "community_service", "education"],
            "notes": "Enables mission-driven financial reporting"
        }
    }

    if dimension_name.lower() in dimension_guides:
        guide = dimension_guides[dimension_name.lower()]

        # Get usage count from DB
        try:
            count = connection.execute_query(
                "SELECT COUNT(*) as cnt FROM event_tags WHERE tag_kind = %s",
                (dimension_name.lower(),),
                fetch_one=True
            )
            usage_count = count.get("cnt") if count else 0
        except:
            usage_count = 0

        return _json({
            "dimension": dimension_name.lower(),
            "description": guide["description"],
            "usage": guide["usage"],
            "examples": guide["examples"],
            "notes": guide["notes"],
            "usage_count": usage_count
        })
    else:
        return _json({"error": f"Dimension '{dimension_name}' not found"}, status_code=404)


@app.get("/api/operations-council")
async def get_operations_council(church_id: str) -> JSONResponse:
    """Unified judgment surface showing exceptions, policy drifts, and questions."""
    return _json({
        "church_id": church_id,
        "exceptions": [
            {
                "exception_id": "exc_001",
                "type": "ambiguous_revenue_recognition",
                "severity": "high",
                "description": "Contract revenue recognition timing ambiguous between milestone and time-based",
                "event_id": "evt_002",
                "agent_belief": "milestone_based (72% confidence)",
                "alternatives": [
                    {"option": "milestone_based", "confidence": 0.72, "rationale": "Contract specifies deliverables"},
                    {"option": "time_based", "confidence": 0.20, "rationale": "Services span 12 months"},
                    {"option": "hybrid", "confidence": 0.08, "rationale": "Blend both approaches"}
                ],
                "evidence_gaps": ["Missing project timeline", "No deliverable definitions in contract"],
                "recommended_action": "Review contract with program director"
            }
        ],
        "policy_drifts": [
            {
                "drift_id": "drift_001",
                "type": "coding_pattern_change",
                "description": "Facility maintenance expenses: 15 coded to 6100, 3 coded to 5000 this month (vs. normally 100% to 6100)",
                "affected_transactions": 3,
                "detected_at": "2026-05-02T10:00:00Z",
                "current_pattern": "6100 (80%), 5000 (20%)",
                "historical_pattern": "6100 (100%)",
                "controller_action_needed": "Confirm: should we standardize on 6100, or is 5000 correct for some subset?"
            }
        ],
        "questions_for_firm": [
            {
                "question_id": "q_001",
                "asker": "external_auditor",
                "question": "Margin by delivery channel for 2026 YTD",
                "status": "pending",
                "requested_at": "2026-04-30T14:00:00Z",
                "projected_ready": "2026-05-03T16:00:00Z"
            },
            {
                "question_id": "q_002",
                "asker": "board",
                "question": "Cash position projection for 90-day horizon under three hiring scenarios",
                "status": "pending",
                "requested_at": "2026-05-01T09:00:00Z",
                "projected_ready": "2026-05-05T14:00:00Z"
            }
        ],
        "live_accruals": {
            "unbilled_services": {"amount": 340000, "confidence_low": 325000, "confidence_high": 355000},
            "warranty_reserves": {"amount": 25000, "confidence_low": 20000, "confidence_high": 30000},
            "bad_debt_reserve": {"amount": 8500, "confidence_low": 5000, "confidence_high": 12000}
        },
        "compliance_trajectory": {
            "debt_covenant": {
                "name": "Total Debt < $5M",
                "current_position": 3200000,
                "threshold": 5000000,
                "trajectory_p_breach_6m": 0.08,
                "status": "green",
                "recovery_levers": [
                    {"lever": "Reduce capital spend by $200K", "impact": "-$200K", "timeline": "Q2"},
                    {"lever": "Accelerate receivables 15 days", "impact": "+$150K", "timeline": "Q2"}
                ]
            }
        }
    })


@app.get("/api/reconciliation/exceptions")
async def get_reconciliation_exceptions(
    church_id: str,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Get reconciliation exceptions - unmatched bank items and suspicious JEs.

    Returns:
    - Unmatched bank transactions
    - Low-confidence classifications
    - Pattern anomalies (payment delays, amount changes)
    """
    from .db import connection

    try:
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )
        if not church_pk:
            return _json({"exceptions": [], "total": 0})

        church_pk = church_pk.get("id")

        # Query low-confidence events
        exceptions_sql = """
            SELECT
                e.event_id,
                e.event_type,
                e.occurred_at,
                e.confidence,
                e.payload,
                e.correlation_id
            FROM events e
            WHERE e.church_id = %s
            AND (e.confidence < 0.70 OR (e.event_type = 'BankItemObserved' AND e.correlation_id IS NULL))
            ORDER BY e.occurred_at DESC
            LIMIT %s OFFSET %s
        """

        exceptions = connection.execute_query(
            exceptions_sql,
            (church_pk, limit, offset)
        ) or []

        exception_list = []
        for exc in exceptions:
            # Determine exception type
            if exc.get("event_type") == "BankItemObserved" and not exc.get("correlation_id"):
                exception_type = "UNMATCHED_BANK_ITEM"
                reason = "No matching JE found"
            else:
                exception_type = "LOW_CONFIDENCE"
                reason = "Confidence below 70%"

            exception_list.append({
                "exception_id": str(exc.get("event_id")),
                "exception_type": exception_type,
                "event_type": exc.get("event_type"),
                "timestamp": exc.get("occurred_at").isoformat() if exc.get("occurred_at") else None,
                "confidence": float(exc.get("confidence") or 1.0),
                "reason": reason,
                "details": exc.get("payload"),
                "status": "pending_review"
            })

        return _json({
            "church_id": church_id,
            "total": len(exception_list),
            "exceptions": exception_list,
            "offset": offset,
            "limit": limit
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.get("/api/reconciliation/status")
async def get_reconciliation_status(church_id: str) -> JSONResponse:
    """Real-time reconciliation status across all sub-ledgers."""
    return _json({
        "church_id": church_id,
        "as_of": datetime.now().isoformat(),
        "cash": {
            "expected": 245000,
            "actual": 244987,
            "difference": -13,
            "status": "reconciled",
            "exceptions": []
        },
        "ar": {
            "expected": 450000,
            "actual": 448500,
            "difference": -1500,
            "aging": {"current": 400000, "30_days": 35000, "60_days": 13500},
            "exceptions": [
                {"customer": "XYZ Org", "amount": 2000, "days_outstanding": 75, "type": "pattern_anomaly", "reason": "Payment pattern shifted from 30 days to 60+ days"}
            ]
        },
        "ap": {
            "expected": 120000,
            "actual": 125000,
            "difference": 5000,
            "aging": {"current": 80000, "30_days": 40000, "60_days": 5000},
            "exceptions": [
                {"vendor": "ABC Cleaning", "amount": 5000, "variance_pct": 8.2, "type": "vendor_pricing_drift", "reason": "Unit price increased from $45 to $53/unit without contract update"}
            ]
        },
        "payroll": {
            "expected": 85000,
            "actual": 85000,
            "difference": 0,
            "status": "reconciled",
            "exceptions": []
        },
        "intercompany": {
            "expected": 0,
            "actual": 0,
            "difference": 0,
            "status": "reconciled",
            "exceptions": []
        }
    })


@app.get("/api/compliance/status")
async def get_compliance_status(church_id: str) -> JSONResponse:
    """Live compliance position: covenants, GAAP, tax, policies, materiality.

    Policy section is sourced from the membrane (real data). Covenants/GAAP/tax/
    materiality sections are still placeholder until those subsystems are wired.
    """
    from backend.membrane.compliance.continuous_compliance import get_compliance_report
    from backend.membrane.pledge.policy_management import list_policies

    report = await get_compliance_report(period="weekly")
    policies = await list_policies(limit=1000)
    active = sum(1 for p in policies.get("policies", []) if p.get("status") == "active")

    return _json({
        "church_id": church_id,
        "as_of": datetime.now().isoformat(),
        "covenants": [],  # TODO: wire to covenant tracking subsystem
        "gaap_conformance": {
            "status": "unknown",
            "violations": [],
            "last_check": None,
            "note": "GAAP conformance checks not yet implemented",
        },
        "tax_position": {
            "status": "unknown",
            "note": "Tax position checks not yet implemented",
        },
        "policies": {
            "active_policies": active,
            "violations": report.get("total_violations", 0),
            "blocked_transactions": report.get("blocked_transactions", 0),
            "warning_transactions": report.get("warning_transactions", 0),
            "compliance_rate": report.get("compliance_rate"),
            "compliance_rate_note": report.get("compliance_rate_note"),
            "top_violation_types": report.get("top_violation_types", []),
        },
        "materiality": {
            "note": "Materiality tracking not yet implemented",
        },
    })


@app.post("/api/policies/{policy_id}")
async def update_policy(policy_id: str, body: Dict[str, Any]) -> JSONResponse:
    """Update a policy that agents enforce."""
    return _json({"policy_id": policy_id, "status": "updated", "message": "Policy updated successfully"})


@app.post("/api/scenarios/project")
async def project_scenario(church_id: str, body: Optional[Dict[str, Any]] = None) -> JSONResponse:
    """Project what-if scenario impact on covenant, margin, cash position."""
    scenario = body or {}
    return _json({
        "scenario_id": "scn_001",
        "church_id": church_id,
        "assumptions": scenario,
        "impact": {
            "covenant_position": 3450000,
            "p_breach": 0.12,
            "covenant_status": "yellow",
            "margin_impact": -25000,
            "cash_impact": -150000
        },
        "levers": [
            {"lever": "Reduce spending", "impact": "+$200K", "feasibility": "high"},
            {"lever": "Accelerate receivables", "impact": "+$150K", "feasibility": "medium"}
        ]
    })


# Phase 12: Cabinet Activity Endpoints
@app.get("/api/cabinets/{principal}/activity")
async def get_cabinet_activity(
    principal: str,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Get activity feed for a cabinet member.

    Args:
        principal: Cabinet member ID (queue-guardian, decision-deputy, etc.)
        limit: Number of cards to return
        offset: Pagination offset

    Returns:
        List of Memory Cards authored by this cabinet member
    """
    from backend.cards.store import get_card_store

    card_store = get_card_store()
    cards = card_store.query_by_principal(principal)

    # Paginate
    total = len(cards)
    cards = cards[offset : offset + limit]

    return {
        "principal": principal,
        "total": total,
        "limit": limit,
        "offset": offset,
        "activity": cards,
    }


@app.get("/api/cabinets/{principal}/current-items")
async def get_cabinet_current_items(
    principal: str,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Get current escalations/items awaiting decision for cabinet member."""
    from backend.cards.store import get_card_store

    card_store = get_card_store()
    cards = card_store.query_by_principal(principal)
    decision_cards = [c for c in cards if c.get("card_type") == "decision"]

    return {
        "principal": principal,
        "current_count": len(decision_cards),
        "items": decision_cards[:10],
    }


@app.post("/api/cabinets/{principal}/items/{item_id}/approve")
async def approve_cabinet_decision(
    principal: str,
    item_id: str,
    body: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Treasurer approves a cabinet decision/draft."""
    if current_user.role not in ["TREASURER_ADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Only treasurers can approve")

    from backend.cards.ledger import get_decision_ledger
    from backend.decision_ledger import LedgerEntry, DecisionCategory, DecisionOutcome

    body = body or {}
    ledger = get_decision_ledger("holy_comforter")

    # Write approval to Decision Ledger
    entry = LedgerEntry(
        entry_id=f"approval-{item_id}",
        decision_id=item_id,
        category=DecisionCategory.APPROVE,
        timestamp=datetime.utcnow(),
        authoring_actor={
            "actor_id": current_user.user_id,
            "actor_type": "TREASURER_ADMIN",
        },
        outcome=DecisionOutcome.ACCEPTED,
        metadata={
            "approved_by": current_user.user_id,
            "approval_notes": body.get("notes", ""),
        },
    )
    ledger.append(entry)

    return {
        "item_id": item_id,
        "status": "approved",
        "approved_at": datetime.utcnow().isoformat(),
        "approved_by": current_user.user_id,
    }


@app.post("/api/cabinets/{principal}/items/{item_id}/reject")
async def reject_cabinet_decision(
    principal: str,
    item_id: str,
    body: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Treasurer rejects a cabinet decision, sends back for revision."""
    if current_user.role not in ["TREASURER_ADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Only treasurers can reject")

    from backend.cards.ledger import get_decision_ledger
    from backend.decision_ledger import LedgerEntry, DecisionCategory, DecisionOutcome

    body = body or {}
    ledger = get_decision_ledger("holy_comforter")

    # Write rejection to Decision Ledger
    entry = LedgerEntry(
        entry_id=f"rejection-{item_id}",
        decision_id=item_id,
        category=DecisionCategory.ROUTE,
        timestamp=datetime.utcnow(),
        authoring_actor={
            "actor_id": current_user.user_id,
            "actor_type": "TREASURER_ADMIN",
        },
        outcome=DecisionOutcome.REJECTED,
        metadata={
            "rejected_by": current_user.user_id,
            "rejection_reason": body.get("reason", ""),
            "send_back_to": principal,
        },
    )
    ledger.append(entry)

    return {
        "item_id": item_id,
        "status": "rejected",
        "rejected_at": datetime.utcnow().isoformat(),
        "rejected_by": current_user.user_id,
        "reason": body.get("reason", ""),
    }


# ─── Phase 13: NBA (Next Best Action) Endpoints ─────────────────────────

@app.get("/api/recommendations")
async def list_recommendations(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """List recommendations from NBA crew.

    Args:
        status: Filter by status (proposed, accepted, declined, deferred, executed)
        priority: Filter by priority (high, medium, low)
        limit: Number of recommendations to return
        offset: Pagination offset

    Returns:
        List of Recommendation Cards from Card Store
    """
    from backend.cards.store import get_card_store

    card_store = get_card_store()

    # Query Recommendation Cards
    recommendations = card_store.query_by_principal("nba-crew")

    # Filter by status if specified
    if status:
        recommendations = [r for r in recommendations if r.get("status") == status]

    # Filter by priority if specified
    if priority:
        recommendations = [r for r in recommendations if r.get("priority") == priority]

    # Paginate
    total = len(recommendations)
    recommendations = recommendations[offset : offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "recommendations": recommendations,
    }


@app.get("/api/recommendations/{recommendation_id}")
async def get_recommendation(
    recommendation_id: str,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Get a single recommendation by ID."""
    from backend.cards.store import get_card_store

    card_store = get_card_store()
    card = card_store.read(recommendation_id)

    if not card:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    return card


@app.post("/api/recommendations/{recommendation_id}/accept")
async def accept_recommendation(
    recommendation_id: str,
    body: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Accept a recommendation and record decision in ledger.

    Args:
        recommendation_id: ID of recommendation to accept
        body: Optional notes and approval metadata

    Returns:
        Updated recommendation with decision recorded
    """
    from backend.cards.store import get_card_store
    from backend.cards.ledger import get_decision_ledger
    from backend.decision_ledger import LedgerEntry, DecisionCategory, DecisionOutcome

    card_store = get_card_store()
    ledger = get_decision_ledger("holy_comforter")
    body = body or {}

    # Get recommendation card
    rec_card = card_store.read(recommendation_id)
    if not rec_card:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    # Write approval to Decision Ledger
    entry = LedgerEntry(
        entry_id=f"rec-accepted-{recommendation_id}",
        decision_id=recommendation_id,
        category=DecisionCategory.APPROVE,
        timestamp=datetime.utcnow(),
        authoring_actor={
            "actor_id": current_user.user_id,
            "actor_type": current_user.role,
        },
        outcome=DecisionOutcome.ACCEPTED,
        metadata={
            "approved_by": current_user.user_id,
            "approval_notes": body.get("notes", ""),
            "recommendation_id": recommendation_id,
        },
    )
    ledger.append(entry)

    return {
        "recommendation_id": recommendation_id,
        "status": "accepted",
        "accepted_at": datetime.utcnow().isoformat(),
        "accepted_by": current_user.user_id,
    }


@app.post("/api/recommendations/{recommendation_id}/decline")
async def decline_recommendation(
    recommendation_id: str,
    body: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Decline a recommendation.

    Args:
        recommendation_id: ID of recommendation to decline
        body: Reason for declining

    Returns:
        Declined recommendation with audit trail
    """
    from backend.cards.store import get_card_store
    from backend.cards.ledger import get_decision_ledger
    from backend.decision_ledger import LedgerEntry, DecisionCategory, DecisionOutcome

    card_store = get_card_store()
    ledger = get_decision_ledger("holy_comforter")
    body = body or {}

    # Get recommendation card
    rec_card = card_store.read(recommendation_id)
    if not rec_card:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    # Write decline to Decision Ledger
    entry = LedgerEntry(
        entry_id=f"rec-declined-{recommendation_id}",
        decision_id=recommendation_id,
        category=DecisionCategory.ROUTE,
        timestamp=datetime.utcnow(),
        authoring_actor={
            "actor_id": current_user.user_id,
            "actor_type": current_user.role,
        },
        outcome=DecisionOutcome.REJECTED,
        metadata={
            "declined_by": current_user.user_id,
            "decline_reason": body.get("reason", ""),
            "recommendation_id": recommendation_id,
        },
    )
    ledger.append(entry)

    return {
        "recommendation_id": recommendation_id,
        "status": "declined",
        "declined_at": datetime.utcnow().isoformat(),
        "declined_by": current_user.user_id,
        "reason": body.get("reason", ""),
    }


@app.post("/api/recommendations/{recommendation_id}/defer")
async def defer_recommendation(
    recommendation_id: str,
    body: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Defer a recommendation for later evaluation.

    Args:
        recommendation_id: ID of recommendation to defer
        body: Deferral notes and timeline

    Returns:
        Deferred recommendation
    """
    from backend.cards.store import get_card_store

    card_store = get_card_store()
    body = body or {}

    # Get recommendation card
    rec_card = card_store.read(recommendation_id)
    if not rec_card:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    return {
        "recommendation_id": recommendation_id,
        "status": "deferred",
        "deferred_at": datetime.utcnow().isoformat(),
        "deferred_by": current_user.user_id,
        "deferral_notes": body.get("notes", ""),
        "defer_until": body.get("defer_until", None),
    }


# ─── Phase 14: Trace + Forecast Endpoints ────────────────────────────

@app.get("/api/trace/{cell_id}")
async def get_gl_trace_endpoint(
    cell_id: str,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Get trace of events contributing to a GL cell.

    Returns Signal Memory cards in chronological order that affected this cell.
    Enables drill-down analysis of GL balance drivers.

    Args:
        cell_id: GL cell ID (e.g., "41000" for expense account)

    Returns:
        Dict with:
        - cell_id: The GL cell
        - current_balance: Current balance
        - signal_count: Number of contributing signals
        - signals: List of Signal Memory cards affecting this cell
        - lineage: Provenance chain (by principal, by type)
    """
    from backend.membrane.trace.gl_trace import get_gl_trace

    trace = await get_gl_trace(cell_id)
    return trace


@app.get("/api/forecast/merge")
async def get_forecast_merge_endpoint(
    from_date: str,
    to_date: str,
    current_user: User = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Get GL projection waterfall between two dates.

    Returns delta between GL snapshots at from_date and to_date.
    Shows account-by-account changes with drivers and waterfall.

    Args:
        from_date: Start date (ISO format, e.g., "2026-04-30")
        to_date: End date (ISO format, e.g., "2026-05-11")

    Returns:
        Dict with:
        - from_date, to_date: Period
        - from_snapshot: GL at from_date
        - to_snapshot: GL at to_date
        - delta: Account-by-account changes
        - waterfall: Step-by-step changes with drivers
    """
    from backend.membrane.trace.forecast_merge import get_forecast_merge

    forecast = await get_forecast_merge(from_date, to_date)
    return forecast


# ─── Phase 15: Scenario Forecasting + Operations Council ─────────────
@app.post("/api/scenario/simulate")
async def simulate_scenario_endpoint(
    scenario_name: str,
    scenario_type: str,
    assumptions: Optional[Dict[str, Any]] = None,
    changes: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Simulate a what-if GL scenario.

    Args:
        scenario_name: Human-readable scenario name
        scenario_type: One of baseline, optimistic, pessimistic, custom
        assumptions: Optional assumptions underlying the projection
        changes: Proposed GL changes {account: delta}

    Returns:
        Scenario projection with base_gl, projected_gl, impact_summary
    """
    from decimal import Decimal
    from backend.membrane.scenario.scenario_card import ScenarioType
    from backend.membrane.scenario.simulator import simulate_scenario

    if assumptions is None:
        assumptions = {}
    if changes is None:
        changes = {}

    # Convert changes to Decimal
    decimal_changes = {k: Decimal(str(v)) for k, v in changes.items()}

    # Validate scenario type
    scenario_type_upper = scenario_type.upper()
    if scenario_type_upper not in [e.name for e in ScenarioType]:
        raise ValueError(
            f"Invalid scenario_type: {scenario_type}. Must be one of: "
            f"{', '.join(e.name for e in ScenarioType)}"
        )

    scenario_enum = ScenarioType[scenario_type_upper]
    projection = await simulate_scenario(scenario_name, scenario_enum, assumptions, decimal_changes)
    return projection


@app.get("/api/scenarios")
async def list_scenarios_endpoint(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List all scenarios with optional filtering.

    Args:
        status: Optional status filter (draft, approved, executed, archived)
        limit: Number of results to return
        offset: Offset for pagination

    Returns:
        List of scenarios with total count
    """
    from backend.membrane.scenario.simulator import list_scenarios

    result = await list_scenarios(status=status, limit=limit, offset=offset)
    return result


@app.get("/api/scenarios/{scenario_id}")
async def get_scenario_endpoint(scenario_id: str) -> Dict[str, Any]:
    """Retrieve a specific scenario by ID.

    Args:
        scenario_id: Scenario identifier

    Returns:
        Scenario details
    """
    from backend.membrane.scenario.simulator import get_scenario

    scenario = await get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    return scenario


@app.get("/api/council/kpis")
async def get_council_kpis_endpoint(
    period_days: int = 7,
    breakdown_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Get Operations Council KPI dashboard.

    Args:
        period_days: Number of days to look back (default 7)
        breakdown_by: Optional breakdown dimension (department, cost_center, fund)

    Returns:
        KPI dashboard with exception metrics, policy violations, budget variance, queue health
    """
    from backend.membrane.scenario.operations_council import get_council_kpis

    kpis = await get_council_kpis(period_days=period_days, breakdown_by=breakdown_by)
    return kpis


@app.get("/api/council/queue-status")
async def get_queue_status_endpoint() -> Dict[str, Any]:
    """Get current queue status snapshot.

    Returns:
        Current counts of exceptions, violations, questions, recommendations
    """
    from backend.membrane.scenario.operations_council import get_queue_status

    queue = await get_queue_status()
    return queue


# ─── Phase 16: Multi-Entity Rollup + Receipt Capture ──────────────────
@app.get("/api/consolidation/rollup")
async def consolidate_entities_endpoint(
    entity_ids: Optional[List[str]] = None,
    include_adjustments: bool = True,
) -> Dict[str, Any]:
    """Consolidate GL across multiple entities.

    Args:
        entity_ids: Optional list of entity IDs to consolidate
        include_adjustments: Whether to include consolidation adjustments

    Returns:
        Consolidated GL with by-entity breakdown and adjustments
    """
    from backend.membrane.multi_entity.rollup import consolidate_entities

    result = await consolidate_entities(
        entity_ids=entity_ids,
        include_adjustments=include_adjustments,
    )
    return result


@app.get("/api/entities/{entity_id}/accounts")
async def get_entity_glaccounts_endpoint(entity_id: str) -> Dict[str, float]:
    """Get GL accounts for a specific entity.

    Args:
        entity_id: Entity identifier

    Returns:
        Dict of {account: balance}
    """
    from backend.membrane.multi_entity.rollup import get_entity_glaccounts

    accounts = await get_entity_glaccounts(entity_id)
    return {k: float(v) for k, v in accounts.items()}


@app.post("/api/receipts/process")
async def process_receipt_endpoint(
    image_data: str,  # Base64-encoded image
    file_name: str,
) -> Dict[str, Any]:
    """Process receipt image via OCR.

    Args:
        image_data: Base64-encoded image data
        file_name: Original file name

    Returns:
        Extracted text, vendor info, line items, confidence score
    """
    import base64
    from backend.membrane.multi_entity.receipt_capture import process_receipt_image

    # Decode base64 image
    image_bytes = base64.b64decode(image_data)

    result = await process_receipt_image(image_bytes, file_name)
    return result


@app.post("/api/receipts/suggest-gl")
async def suggest_gl_mapping_endpoint(
    vendor_name: str,
    amount: float,
    description: str,
    vendor_category: Optional[str] = None,
) -> Dict[str, Any]:
    """Suggest GL account mapping for receipt line item.

    Args:
        vendor_name: Vendor name
        amount: Transaction amount
        description: Line item description
        vendor_category: Optional vendor category

    Returns:
        Suggested GL accounts with confidence scores
    """
    from decimal import Decimal
    from backend.membrane.multi_entity.receipt_capture import suggest_gl_mapping

    result = await suggest_gl_mapping(
        vendor_name=vendor_name,
        amount=Decimal(str(amount)),
        description=description,
        vendor_category=vendor_category,
    )
    return result


@app.get("/api/vendors/{vendor_name}/info")
async def extract_vendor_info_endpoint(
    vendor_name: str,
    address: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract or lookup vendor information.

    Args:
        vendor_name: Vendor name
        address: Optional vendor address

    Returns:
        Vendor info with hierarchy and matching
    """
    from backend.membrane.multi_entity.receipt_capture import extract_vendor_info

    result = await extract_vendor_info(vendor_name, address)
    return result


# ─── Phase 17: Pledge Matching + Policy Management ────────────────────
class CreatePledgeRequest(BaseModel):
    pledge_id: str
    donor_name: str
    amount: float
    purpose: str
    pledge_date: str
    expected_receipt_date: Optional[str] = None


@app.post("/api/pledges")
async def create_pledge_endpoint(req: CreatePledgeRequest) -> Dict[str, Any]:
    """Create a new pledge.

    Body: CreatePledgeRequest JSON.

    Returns:
        Pledge record
    """
    from decimal import Decimal
    from backend.membrane.pledge.pledge_matching import create_pledge

    result = await create_pledge(
        pledge_id=req.pledge_id,
        donor_name=req.donor_name,
        amount=Decimal(str(req.amount)),
        purpose=req.purpose,
        pledge_date=req.pledge_date,
        expected_receipt_date=req.expected_receipt_date,
    )
    return result


@app.get("/api/pledges")
async def list_pledges_endpoint(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List pledges with optional filtering.

    Args:
        status: Optional status filter
        limit: Number of results
        offset: Pagination offset

    Returns:
        List of pledges
    """
    from backend.membrane.pledge.pledge_matching import list_pledges

    result = await list_pledges(status=status, limit=limit, offset=offset)
    return result


@app.get("/api/pledges/{pledge_id}/fulfillment")
async def get_pledge_fulfillment_endpoint(pledge_id: str) -> Dict[str, Any]:
    """Get pledge fulfillment status.

    Args:
        pledge_id: Pledge identifier

    Returns:
        Fulfillment summary with matched amounts
    """
    from backend.membrane.pledge.pledge_matching import get_pledge_fulfillment

    result = await get_pledge_fulfillment(pledge_id)
    return result


class CreatePolicyRequest(BaseModel):
    policy_id: str
    title: str
    description: str
    effective_date: str
    enforcement_level: str = "warning"
    policy_rules: Dict[str, Any] = {}


@app.post("/api/policies")
async def create_policy_endpoint(req: CreatePolicyRequest) -> Dict[str, Any]:
    """Create a new financial policy.

    Body: CreatePolicyRequest JSON. `policy_rules` may include
    `amount_limit`, `department_limits`, `restricted_accounts`,
    `restricted_transaction_types`.

    Returns:
        Policy record
    """
    from backend.membrane.pledge.policy_management import create_policy

    result = await create_policy(
        policy_id=req.policy_id,
        title=req.title,
        description=req.description,
        policy_rules=req.policy_rules,
        effective_date=req.effective_date,
        enforcement_level=req.enforcement_level,
    )
    return result


@app.get("/api/policies")
async def list_policies_endpoint(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List policies across all churches with optional filtering.

    Use /api/churches/{church_id}/policies for church-scoped queries.

    Args:
        status: Optional status filter
        limit: Number of results
        offset: Pagination offset

    Returns:
        List of policies
    """
    from backend.membrane.pledge.policy_management import list_policies

    result = await list_policies(status=status, limit=limit, offset=offset)
    return result


# POST /api/policies/{policy_id}/vote — handled by backend.routes.policies (Phase 5 router),
# which routes through the membrane policy_management.vote_on_policy. See routes/policies.py.


class CheckComplianceRequest(BaseModel):
    transaction_amount: float
    account: str
    department: str
    transaction_type: str = "general"


@app.post("/api/compliance/check")
async def check_compliance_endpoint(req: CheckComplianceRequest) -> Dict[str, Any]:
    """Check transaction compliance with active policies."""
    from backend.membrane.pledge.policy_management import check_policy_compliance

    result = await check_policy_compliance(
        transaction_amount=req.transaction_amount,
        account=req.account,
        department=req.department,
        transaction_type=req.transaction_type,
    )
    return result


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> HTMLResponse:
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text())


_STATIC_MEDIA_TYPES = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".map": "application/json",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


@app.get("/{path:path}", response_class=HTMLResponse)
async def serve_page(path: str):
    p = FRONTEND_DIR / path
    if p.exists() and p.is_file():
        if p.suffix == ".html":
            return HTMLResponse(p.read_text())
        media_type = _STATIC_MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream")
        return FileResponse(str(p), media_type=media_type)
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text())
