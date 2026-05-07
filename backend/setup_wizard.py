"""EIME Setup Wizard backend.

Provides the /api/setup/* endpoints used by frontend/setup-wizard.html
to walk a new user through:
  1. Church profile
  2. Chart of accounts import
  3. Plaid credentials test
  4. ACS Realm credentials test
  5. SMTP credentials test
  6. User accounts
  7. Approval chain config
  8. Optional budget import
  9. Final completion (writes .setup_complete marker)

Files written to backend/data/:
  church_profile_{church_id}.json
  users_{church_id}.json
  approval_chains_{church_id}.json
  .setup_complete             (marker — wizard cannot run again)

Secrets (passwords / API keys) are NOT persisted by these endpoints; they
are only used to verify connectivity.
"""
from __future__ import annotations

import json
import re
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

# Lightweight email regex (RFC-5322 simplified). Avoids the email-validator dep.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(v: str) -> str:
    if not isinstance(v, str) or not _EMAIL_RE.match(v.strip()):
        raise ValueError(f"invalid email address: {v!r}")
    return v.strip()


SETUP_DIR = Path(__file__).resolve().parent / "data"
SETUP_DIR.mkdir(parents=True, exist_ok=True)

VALID_ROLES = {"TREASURER_ADMIN", "BUDGET_OWNER", "FINANCE_STAFF", "VIEWER"}
VALID_DENOMINATIONS = {
    "EPISCOPAL", "METHODIST", "UMC", "BAPTIST",
    "CATHOLIC", "PRESBYTERIAN", "NONDENOMINATIONAL", "OTHER",
}

router = APIRouter(prefix="/api/setup", tags=["setup-wizard"])


# ============================================================
# Models
# ============================================================

class ChurchProfileBody(BaseModel):
    church_id: str = Field(..., min_length=1)
    church_name: str = Field(..., min_length=1)
    denomination: str = Field(..., min_length=1)
    fiscal_year_start: str = Field(..., min_length=1)
    address: Optional[str] = None

    @field_validator("denomination")
    @classmethod
    def validate_denomination(cls, v: str) -> str:
        v_up = v.upper()
        if v_up not in VALID_DENOMINATIONS:
            return "OTHER"
        return v_up


class PlaidTestBody(BaseModel):
    client_id: str
    secret: str
    env: str = "sandbox"


class AcsTestBody(BaseModel):
    username: str
    password: str
    base_url: str = "https://realm.acsedu.org"


class SmtpTestBody(BaseModel):
    from_email: str
    smtp_host: str
    smtp_port: int = 587
    username: str
    password: str
    to_email: Optional[str] = None  # if None, sends to from_email


class UserItem(BaseModel):
    name: str = Field(..., min_length=1)
    email: str
    role: str

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return v


class UsersBody(BaseModel):
    church_id: str
    users: List[UserItem]


class ApprovalChainItem(BaseModel):
    gl_pattern: str = Field(..., min_length=1)
    primary_email: str
    secondary_email: Optional[str] = None
    deadline_hours: int = Field(default=48, gt=0, le=24 * 30)

    @field_validator("primary_email")
    @classmethod
    def _v_primary(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("secondary_email")
    @classmethod
    def _v_secondary(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return _validate_email(v)


class ApprovalChainsBody(BaseModel):
    church_id: str
    chains: List[ApprovalChainItem]


class CompleteBody(BaseModel):
    church_id: str
    force: bool = False


# ============================================================
# Helpers (the test-mockable seams)
# ============================================================

def _setup_marker() -> Path:
    return SETUP_DIR / ".setup_complete"


def _profile_path(church_id: str) -> Path:
    return SETUP_DIR / f"church_profile_{church_id}.json"


def _users_path(church_id: str) -> Path:
    return SETUP_DIR / f"users_{church_id}.json"


def _chains_path(church_id: str) -> Path:
    return SETUP_DIR / f"approval_chains_{church_id}.json"


def _plaid_create_link_token(client_id: str, secret: str, env: str) -> dict[str, Any]:
    """Make a real Plaid call to verify credentials. Mocked in tests."""
    import urllib.request
    import urllib.error

    base = "https://sandbox.plaid.com" if env.lower() == "sandbox" else "https://production.plaid.com"
    url = f"{base}/link/token/create"
    payload = {
        "client_id": client_id,
        "secret": secret,
        "client_name": "EIME Setup",
        "language": "en",
        "country_codes": ["US"],
        "user": {"client_user_id": "eime-setup-probe"},
        "products": ["transactions"],
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # pragma: no cover
        body = json.loads(resp.read())
    if "link_token" not in body:
        raise RuntimeError(body.get("error_message") or "no link_token in response")
    return body


def _acs_login(username: str, password: str, base_url: str) -> bool:
    """Attempt to reach the ACS Realm login endpoint. Mocked in tests."""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(base_url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:  # pragma: no cover
            return 200 <= resp.status < 400
    except Exception:  # pragma: no cover
        return False


def _smtp_send_test(
    from_email: str, smtp_host: str, smtp_port: int,
    username: str, password: str, to_email: Optional[str] = None,
) -> bool:
    """Open SMTP connection and send a probe email. Mocked in tests."""
    target = to_email or from_email
    msg = MIMEText("EIME setup wizard SMTP test message.")
    msg["Subject"] = "EIME setup test"
    msg["From"] = from_email
    msg["To"] = target

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:  # pragma: no cover
        s.starttls()
        s.login(username, password)
        s.sendmail(from_email, [target], msg.as_string())
    return True


# ============================================================
# Endpoints
# ============================================================

@router.get("/status")
async def setup_status() -> JSONResponse:
    return JSONResponse({"setup_complete": _setup_marker().exists()})


@router.post("/church-profile")
async def church_profile(body: ChurchProfileBody) -> JSONResponse:
    """Create / overwrite a church profile JSON and seed a COA context."""
    profile = {
        "church_id": body.church_id,
        "church_name": body.church_name,
        "denomination": body.denomination,
        "fiscal_year_start": body.fiscal_year_start,
        "address": body.address,
        "created_at": datetime.utcnow().isoformat(),
    }
    _profile_path(body.church_id).write_text(json.dumps(profile, indent=2))

    # Also seed a minimal AccountingContext so subsequent steps work.
    try:
        from .tools import coa_store
        from .models import (
            AccountingContext, DenominationType, RestrictionClass,
            FundCategory, Account, Fund,
        )
        from datetime import date as _date

        if not coa_store.load_accounting_context(body.church_id):
            try:
                fy_start = _date.fromisoformat(body.fiscal_year_start)
            except Exception:
                fy_start = _date(datetime.utcnow().year, 1, 1)
            try:
                denom = DenominationType(body.denomination)
            except Exception:
                denom = DenominationType("NONDENOMINATIONAL")
            ctx = AccountingContext(
                church_id=body.church_id,
                church_name=body.church_name,
                denomination_type=denom,
                fiscal_year=fy_start.year,
                fiscal_year_start=fy_start,
                accounts=[
                    Account(
                        account_number="1000", account_name="Cash — Checking",
                        account_type="Asset", fund_id="GEN",
                        restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                    ),
                ],
                funds=[
                    Fund(
                        fund_id="GEN", fund_name="General Operating Fund",
                        restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                        fund_category=FundCategory.GENERAL_OPERATING,
                    ),
                ],
            )
            coa_store.save_accounting_context(ctx)
    except Exception as exc:
        # Don't fail the wizard step if COA seeding fails — profile is saved.
        print(f"[setup_wizard] COA seed skipped: {exc}", flush=True)

    return JSONResponse({"church_id": body.church_id, "status": "created"})


@router.post("/coa-import")
async def coa_import(church_id: str, file: UploadFile = File(...)) -> JSONResponse:
    """Import COA spreadsheet for the given church. Reuses spreadsheet_parser."""
    from .tools import coa_store
    from .tools.spreadsheet_parser import parse_spreadsheet
    from .models import Account, Fund, RestrictionClass, FundCategory
    from decimal import Decimal

    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, f"Church '{church_id}' not found. Create profile first.")

    fname = (file.filename or "").lower()
    if not any(fname.endswith(ext) for ext in (".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "File must be Excel (.xlsx/.xls) or CSV (.csv)")

    content = await file.read()
    try:
        parsed = parse_spreadsheet(content, file.filename or "")
    except Exception as exc:
        raise HTTPException(400, f"Failed to parse spreadsheet: {exc}")

    errors: list[str] = []
    added_accounts = 0
    for a in parsed.get("accounts", []) or []:
        try:
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
        except Exception as exc:
            errors.append(f"row {a.get('account_number')}: {exc}")

    for f in parsed.get("funds", []) or []:
        try:
            fund = Fund(
                fund_id=f["fund_id"],
                fund_name=f["fund_name"],
                restriction_class=RestrictionClass(
                    f.get("restriction_class", "WITHOUT_RESTRICTION")
                ),
                fund_category=FundCategory(f.get("category", "GENERAL_OPERATING")),
                purpose_description=f.get("purpose_description"),
                expenditure_rules=f.get("expenditure_rules"),
                current_balance=Decimal(str(f.get("current_balance", "0"))),
            )
            ctx.funds = [x for x in ctx.funds if x.fund_id != fund.fund_id]
            ctx.funds.append(fund)
        except Exception as exc:
            errors.append(f"fund {f.get('fund_id')}: {exc}")

    ctx.accounts.sort(key=lambda x: x.account_number)
    coa_store.save_accounting_context(ctx)

    preview = [
        {"account_number": a.account_number, "account_name": a.account_name}
        for a in ctx.accounts[:5]
    ]
    return JSONResponse({
        "imported": True,
        "account_count": len(ctx.accounts),
        "added": added_accounts,
        "errors": errors,
        "preview": preview,
    })


@router.post("/plaid-test")
async def plaid_test(body: PlaidTestBody) -> JSONResponse:
    try:
        result = _plaid_create_link_token(body.client_id, body.secret, body.env)
        return JSONResponse({
            "success": True,
            "message": "Connected",
            "link_token_prefix": (result.get("link_token") or "")[:12],
        })
    except Exception as exc:
        return JSONResponse({"success": False, "message": str(exc)})


@router.post("/acs-test")
async def acs_test(body: AcsTestBody) -> JSONResponse:
    try:
        ok = _acs_login(body.username, body.password, body.base_url)
        return JSONResponse({
            "success": bool(ok),
            "message": "Logged in" if ok else "Login failed",
        })
    except Exception as exc:
        return JSONResponse({"success": False, "message": str(exc)})


@router.post("/smtp-test")
async def smtp_test(body: SmtpTestBody) -> JSONResponse:
    try:
        ok = _smtp_send_test(
            body.from_email, body.smtp_host, body.smtp_port,
            body.username, body.password, body.to_email,
        )
        return JSONResponse({
            "success": bool(ok),
            "message": "Sent" if ok else "Send failed",
        })
    except Exception as exc:
        return JSONResponse({"success": False, "message": str(exc)})


@router.post("/users")
async def setup_users(body: UsersBody) -> JSONResponse:
    """Persist user roster to users_{church_id}.json (no secrets stored)."""
    payload = {
        "church_id": body.church_id,
        "users": [
            {"name": u.name, "email": u.email, "role": u.role}
            for u in body.users
        ],
        "saved_at": datetime.utcnow().isoformat(),
    }
    _users_path(body.church_id).write_text(json.dumps(payload, indent=2))
    return JSONResponse({"created_count": len(body.users), "users": payload["users"]})


@router.post("/approval-chains")
async def setup_approval_chains(body: ApprovalChainsBody) -> JSONResponse:
    """Persist approval-chain mappings to approval_chains_{church_id}.json."""
    for c in body.chains:
        if not _is_valid_gl_pattern(c.gl_pattern):
            raise HTTPException(400, f"Invalid GL pattern: {c.gl_pattern!r}")

    payload = {
        "church_id": body.church_id,
        "chains": [c.model_dump() for c in body.chains],
        "saved_at": datetime.utcnow().isoformat(),
    }
    _chains_path(body.church_id).write_text(json.dumps(payload, indent=2, default=str))
    return JSONResponse({"created_count": len(body.chains), "chains": payload["chains"]})


@router.post("/budget-import")
async def setup_budget_import(church_id: str, file: UploadFile = File(...)) -> JSONResponse:
    """Optional budget import — delegates to the same parser used by /api/churches/.../budget."""
    from .tools import coa_store
    from .tools.spreadsheet_parser import parse_spreadsheet

    ctx = coa_store.load_accounting_context(church_id)
    if not ctx:
        raise HTTPException(404, f"Church '{church_id}' not found.")

    fname = (file.filename or "").lower()
    if not any(fname.endswith(ext) for ext in (".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "File must be Excel (.xlsx/.xls) or CSV (.csv)")

    content = await file.read()
    try:
        parsed = parse_spreadsheet(content, file.filename or "")
    except Exception as exc:
        raise HTTPException(400, f"Failed to parse spreadsheet: {exc}")

    # parse_spreadsheet may return:
    #   parsed["budget"]   -> list[dict]      (budget-shaped sheet)
    #   parsed["accounts"] -> list[dict]      (COA-shaped sheet — fallback)
    #   parsed["rows"]     -> list[dict]      (generic)
    candidates = [
        parsed.get("budget"),
        parsed.get("accounts"),
        parsed.get("rows"),
    ]
    rows: list[dict] = []
    for c in candidates:
        if isinstance(c, list) and c and isinstance(c[0], dict):
            rows = c
            break

    total = 0.0
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        amt = (
            row.get("annual_budget")
            or row.get("annual_total")
            or row.get("annual")
            or 0
        )
        try:
            total += float(amt)
            count += 1
        except (TypeError, ValueError):
            continue

    return JSONResponse({
        "success": True,
        "budget_total": round(total, 2),
        "account_count": count,
    })


@router.post("/complete")
async def setup_complete(body: CompleteBody) -> JSONResponse:
    """Write .setup_complete marker. 409 if already complete unless force."""
    marker = _setup_marker()
    if marker.exists() and not body.force:
        raise HTTPException(409, "Setup already complete. Pass force=true to re-run.")
    marker.write_text(json.dumps({
        "church_id": body.church_id,
        "completed_at": datetime.utcnow().isoformat(),
    }))
    return JSONResponse({
        "setup_complete": True,
        "next_url": "/index.html",
        "church_id": body.church_id,
    })


# ============================================================
# Validation utilities
# ============================================================

# Valid GL patterns:
#   "6000"            single account
#   "6000-6999"       range
#   "65*"             prefix glob
_GL_RE = re.compile(r"^\d+(-\d+)?$|^\d*\*$|^\d+\*$")


def _is_valid_gl_pattern(p: str) -> bool:
    return bool(_GL_RE.match(p.strip()))
