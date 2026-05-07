"""EIME FastAPI application — Embark Invoice Mapping Engine."""
from __future__ import annotations
import asyncio
import json
import os
import shutil
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

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import (
    Account, AccountingContext, AllocationSchedule, ApportionmentAccount,
    ApprovalChain, BudgetMonth, BudgetPlan, ChatRequest, DenominationType,
    DocumentType, Fund, FundCategory, HITLDecisions, HITLLineDecision,
    ProcessingStatus, RestrictionClass,
)
from .tools import coa_store
from .tools.spreadsheet_parser import parse_spreadsheet
from .tools import approval_chain_resolver, approval_audit
from .integrations.email import tokens as email_tokens
from . import flow
from . import scheduler as approval_scheduler

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _json(data: Any) -> JSONResponse:
    return JSONResponse(content=json.loads(json.dumps(data, cls=_Encoder, default=str)))


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
async def ytd_reset(church_id: str, body: YTDResetBody) -> JSONResponse:
    """Reset YTD actuals to zero. Requires explicit confirmation."""
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

    _persist_je(je.church_id, je.model_dump())

    return _json({
        "ok": True,
        "entry_id": je.entry_id,
        "status": je.status.value if hasattr(je.status, "value") else str(je.status),
        "journal_entry": je.model_dump(),
    })


@app.get("/api/churches/{church_id}/jes/manual")
async def list_manual_jes(church_id: str) -> JSONResponse:
    """List manually-created JEs for a church."""
    path = _jes_path(church_id)
    if not path.exists():
        return _json([])
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return _json(out)


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
async def replace_approval_chains(church_id: str,
                                  body: List[ApprovalChainBody]) -> JSONResponse:
    chains = [ApprovalChain(**c.model_dump()) for c in body]
    approval_chain_resolver.save_chains(church_id, chains)
    return _json({"ok": True, "count": len(chains)})


@app.post("/api/churches/{church_id}/approval-chains")
async def add_approval_chain(church_id: str,
                             body: ApprovalChainBody) -> JSONResponse:
    chain = ApprovalChain(**body.model_dump())
    chains = approval_chain_resolver.add_chain(church_id, chain)
    return _json({"ok": True, "count": len(chains)})


@app.delete("/api/churches/{church_id}/approval-chains/{chain_id}")
async def delete_approval_chain(church_id: str, chain_id: str) -> JSONResponse:
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

    if action.upper() == "REJECT":
        job.status = ProcessingStatus.REJECTED
        job.updated_at = datetime.utcnow()
        body_html = (
            "<html><body><h2>Decision recorded: REJECTED</h2>"
            "<p>The invoice has been rejected and will not be posted.</p>"
            "</body></html>"
        )
    else:
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
async def treasurer_decision(job_id: str, body: TreasurerDecisionBody,
                             background_tasks: BackgroundTasks) -> JSONResponse:
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


# ===== FR-06.4 / FR-06.5: JE state machine + ACS Realm posting =====

def _find_journal_entry(je_id: str):
    """Find a JE by ID across processing jobs and manual JE files.

    Returns (JournalEntry, church_id) or (None, None).
    """
    from .models.schemas import JournalEntry as _JE
    # Check processing jobs first
    for job in flow.list_jobs():
        if job.journal_entry and job.journal_entry.entry_id == je_id:
            return job.journal_entry, job.church_id

    # Check manual JE files
    for f in JE_DATA_DIR.glob("jes_*.jsonl"):
        cid = f.stem.replace("jes_", "")
        try:
            content = f.read_text()
        except Exception:
            continue
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                je_data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if je_data.get("entry_id") == je_id:
                try:
                    return _JE(**je_data), cid
                except Exception:
                    continue
    return None, None


def _update_je_in_store(je: Any, church_id: str) -> None:
    """Update an existing JE in its source (processing job or manual JE file).

    Note: distinct from `_persist_je(church_id, je_dict)` which appends a new
    entry. This one finds-and-replaces by entry_id.
    """
    je_data = je.model_dump() if hasattr(je, "model_dump") else dict(je)

    # If JE lives on a processing job, mutate in-place there.
    for job in flow.list_jobs():
        if job.journal_entry and job.journal_entry.entry_id == je.entry_id:
            job.journal_entry = je
            return

    # Otherwise find/replace in jes_{church_id}.jsonl.
    f = _jes_path(church_id)
    if not f.exists():
        JE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(je_data, default=str) + "\n")
        return

    lines = f.read_text().splitlines()
    out_lines: List[str] = []
    found = False
    for ln in lines:
        if not ln.strip():
            continue
        try:
            data = json.loads(ln)
        except json.JSONDecodeError:
            out_lines.append(ln)
            continue
        if data.get("entry_id") == je.entry_id:
            out_lines.append(json.dumps(je_data, default=str))
            found = True
        else:
            out_lines.append(ln)
    if not found:
        out_lines.append(json.dumps(je_data, default=str))
    f.write_text("\n".join(out_lines) + "\n")


@app.post("/api/jes/{je_id}/post")
async def post_je_to_acs(je_id: str) -> JSONResponse:
    """Post an APPROVED journal entry to ACS Realm via browser automation."""
    from .models.schemas import JEStatus
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
        _update_je_in_store(je, church_id)
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
) -> JSONResponse:
    """List journal entries with optional filtering (FR-06.4)."""
    jes: List[Dict[str, Any]] = []

    # Read from jes_{church_id}.jsonl files
    if church_id:
        je_files = [_jes_path(church_id)]
    else:
        je_files = list(JE_DATA_DIR.glob("jes_*.jsonl"))

    for f in je_files:
        if not f.exists():
            continue
        cid = f.stem.replace("jes_", "")
        try:
            content = f.read_text()
        except Exception:
            continue
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                je_data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if status and je_data.get("status") != status:
                continue
            jes.append({**je_data, "church_id": je_data.get("church_id", cid)})

    # Also include JEs from ProcessingJobs
    for job in flow.list_jobs():
        if church_id and job.church_id != church_id:
            continue
        if job.journal_entry:
            je_obj = job.journal_entry
            je_dict = (
                je_obj.model_dump()
                if hasattr(je_obj, "model_dump")
                else dict(je_obj)
            )
            if status and je_dict.get("status") != status:
                continue
            jes.append({
                **je_dict,
                "church_id": job.church_id,
                "job_id": job.job_id,
            })

    return _json(jes)


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> HTMLResponse:
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text())


@app.get("/{path:path}", response_class=HTMLResponse)
async def serve_page(path: str) -> HTMLResponse:
    p = FRONTEND_DIR / path
    if p.exists() and p.suffix == ".html":
        return HTMLResponse(p.read_text())
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text())
