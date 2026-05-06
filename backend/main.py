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
    BudgetMonth, BudgetPlan, ChatRequest, DenominationType, DocumentType,
    Fund, FundCategory, HITLDecisions, HITLLineDecision, ProcessingStatus,
    RestrictionClass,
)
from .tools import coa_store
from .tools.spreadsheet_parser import parse_spreadsheet
from . import flow

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
    result = await route_question(question=body.question, job=job)
    return _json(result)


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

@app.get("/", response_class=HTMLResponse)
async def serve_index() -> HTMLResponse:
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text())


@app.get("/{path:path}", response_class=HTMLResponse)
async def serve_page(path: str) -> HTMLResponse:
    p = FRONTEND_DIR / path
    if p.exists() and p.suffix == ".html":
        return HTMLResponse(p.read_text())
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text())
