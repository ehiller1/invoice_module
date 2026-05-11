"""COA persistence + embedding-based semantic search per FRS §9.13.

Backed by ChromaDB with the all-MiniLM-L6-v2 embedding model.
Per-church collection isolation; rebuilt on COA mutation.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from ..models import (
    Account, AccountingContext, AllocationSchedule, ApportionmentAccount,
    DenominationType, Fund, FundCategory, RestrictionClass,
)
from datetime import date
from decimal import Decimal


DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
DATA_ROOT.mkdir(exist_ok=True)
CHROMA_DIR = DATA_ROOT / "chroma"
CHROMA_DIR.mkdir(exist_ok=True)


_embed_fn = None
_chroma_client: Optional[chromadb.PersistentClient] = None


def _get_embed_fn():
    """Lazy-initialize the embedding function on first use."""
    global _embed_fn
    if _embed_fn is None:
        _embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
    return _embed_fn


def _client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client


def _ctx_path(church_id: str) -> Path:
    return DATA_ROOT / f"context_{church_id}.json"


def _coll_name(church_id: str) -> str:
    return f"coa_{church_id}"


# ===== Persistence =====

def save_accounting_context(ctx: AccountingContext) -> None:
    _ctx_path(ctx.church_id).write_text(ctx.model_dump_json(indent=2))
    _rebuild_index(ctx)


def load_accounting_context(church_id: str) -> Optional[AccountingContext]:
    p = _ctx_path(church_id)
    if not p.exists():
        return None
    raw = json.loads(p.read_text())
    return AccountingContext.model_validate(raw)


def list_churches() -> List[Dict]:
    out = []
    for p in DATA_ROOT.glob("context_*.json"):
        try:
            data = json.loads(p.read_text())
            out.append({
                "church_id": data["church_id"],
                "church_name": data.get("church_name", data["church_id"]),
                "denomination_type": data.get("denomination_type", "OTHER"),
                "account_count": len(data.get("accounts", [])),
                "fund_count": len(data.get("funds", [])),
            })
        except Exception:
            continue
    return out


# ===== Embedding index =====

def _rebuild_index(ctx: AccountingContext) -> None:
    coll_name = _coll_name(ctx.church_id)
    client = _client()
    try:
        client.delete_collection(coll_name)
    except Exception:
        pass
    coll = client.create_collection(
        name=coll_name,
        embedding_function=_get_embed_fn(),
        metadata={"church_id": ctx.church_id},
    )
    fund_lookup = {f.fund_id: f for f in ctx.funds}
    docs: List[str] = []
    metas: List[Dict] = []
    ids: List[str] = []
    for acct in ctx.accounts:
        if not acct.active:
            continue
        fund = fund_lookup.get(acct.fund_id)
        fund_name = fund.fund_name if fund else acct.fund_id
        # Rich semantic doc: account name + range hint + fund context
        doc = f"{acct.account_name} (account {acct.account_number}, {acct.account_type}) | fund: {fund_name}"
        docs.append(doc)
        metas.append({
            "account_number": acct.account_number,
            "account_name": acct.account_name,
            "account_type": acct.account_type,
            "fund_id": acct.fund_id,
            "fund_name": fund_name,
            "restriction_class": acct.restriction_class
                if isinstance(acct.restriction_class, str)
                else acct.restriction_class.value,
        })
        ids.append(f"{acct.account_number}_{acct.fund_id}")
    if docs:
        coll.add(documents=docs, metadatas=metas, ids=ids)


def semantic_search(church_id: str, query: str, k: int = 5,
                    fund_filter: Optional[List[str]] = None) -> List[Dict]:
    """Search the church's COA semantically. Returns top-k {account, fund, score}."""
    coll_name = _coll_name(church_id)
    client = _client()
    try:
        coll = client.get_collection(coll_name, embedding_function=_get_embed_fn())
    except Exception:
        return []
    where = None
    if fund_filter:
        where = {"fund_id": {"$in": fund_filter}}
    res = coll.query(query_texts=[query], n_results=max(k, 1), where=where)
    out: List[Dict] = []
    metas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    for meta, dist in zip(metas, distances):
        out.append({
            **meta,
            "score": float(1.0 - min(dist, 1.0)),
        })
    return out


# ===== Sample / seed data =====

def seed_sample_church() -> AccountingContext:
    """Build a realistic sample COA for a UMC church to make the demo concrete."""
    funds = [
        Fund(fund_id="GEN", fund_name="General Operating",
             restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
             fund_category=FundCategory.GENERAL_OPERATING,
             purpose_description="Day-to-day ministry and operations",
             expenditure_rules="Unrestricted - any operating expense",
             current_balance=Decimal("85000")),
        Fund(fund_id="BLDG", fund_name="Building Fund",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
             fund_category=FundCategory.CAPITAL_CAMPAIGN,
             purpose_description="Capital improvements to facilities",
             expenditure_rules="Construction, major HVAC, capital equipment only",
             current_balance=Decimal("142000")),
        Fund(fund_id="MISS", fund_name="World Missions Fund",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
             fund_category=FundCategory.TEMP_RESTRICTED_PURPOSE,
             purpose_description="Support of missionaries and mission organizations",
             expenditure_rules="Pass-through to registered missionary organizations",
             current_balance=Decimal("28500")),
        Fund(fund_id="YOUTH", fund_name="Youth Ministry Fund",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
             fund_category=FundCategory.TEMP_RESTRICTED_PURPOSE,
             purpose_description="Youth retreats, materials, scholarships",
             expenditure_rules="Youth ministry expenses only (ministry_area=YOUTH)",
             current_balance=Decimal("9750")),
        Fund(fund_id="BENEV", fund_name="Pastor's Benevolence Fund",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
             fund_category=FundCategory.BOARD_DESIGNATED,
             purpose_description="Aid to individuals in need",
             expenditure_rules="IRS substantiation required; pastor discretion",
             current_balance=Decimal("4200")),
        Fund(fund_id="ENDOW", fund_name="Smith Endowment",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PERMANENT,
             fund_category=FundCategory.PERMANENTLY_RESTRICTED,
             purpose_description="Principal preserved; income funds music ministry",
             expenditure_rules="Income only; principal never spent",
             current_balance=Decimal("250000")),
    ]
    accounts: List[Account] = []

    def add(num: str, name: str, atype: str, fund: str, rc: RestrictionClass) -> None:
        accounts.append(Account(account_number=num, account_name=name, account_type=atype,
                                fund_id=fund, restriction_class=rc))

    # Assets
    add("1010", "Operating Cash", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1020", "Building Fund Cash", "Asset", "BLDG", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("1030", "Missions Cash", "Asset", "MISS", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("1500", "Land", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1510", "Buildings", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1520", "Equipment - Office", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1530", "Equipment - HVAC", "Asset", "BLDG", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("1540", "Vehicles", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # Liabilities
    add("2010", "Accounts Payable", "Liability", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("2020", "Designated Gifts Liability", "Liability", "MISS", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("2030", "Payroll Liabilities", "Liability", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # Net Assets
    add("3100", "Net Assets - Without Restriction", "Equity", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("3200", "Net Assets - Purpose Restricted", "Equity", "MISS", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("3300", "Net Assets - Endowment", "Equity", "ENDOW", RestrictionClass.WITH_RESTRICTION_PERMANENT)

    # Revenue
    add("4100", "Tithes & Offerings", "Revenue", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("4200", "Designated Gifts - Building", "Revenue", "BLDG", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("4210", "Designated Gifts - Missions", "Revenue", "MISS", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("4220", "Designated Gifts - Youth", "Revenue", "YOUTH", RestrictionClass.WITH_RESTRICTION_PURPOSE)

    # Personnel (5000)
    add("5100", "Clergy Compensation - Salary", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5101", "Clergy Compensation - Housing Allowance", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5102", "Clergy Compensation - Parsonage Utilities", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5110", "SECA Reimbursement", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5200", "Lay Staff Wages", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5300", "Employee Benefits - Health", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5310", "Employee Benefits - Retirement", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # Ministry programs (6000)
    add("6100", "Worship - Music", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6110", "Worship - Altar & Communion", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6200", "Children's Ministry", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6300", "Youth Ministry - General", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6310", "Youth Ministry - Restricted", "Expense", "YOUTH", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("6400", "Adult Education", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6500", "Missions - Local", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6600", "Missions - Pass-Through Disbursements", "Expense", "MISS", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("6700", "Pastoral Care", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6900", "Benevolence Disbursements", "Expense", "BENEV", RestrictionClass.WITH_RESTRICTION_PURPOSE)

    # Facility & Operations (7000)
    add("7100", "Mortgage / Rent", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7200", "Utilities - Electric", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7210", "Utilities - Gas", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7220", "Utilities - Water/Sewer", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7230", "Utilities - Internet/Phone", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7300", "Maintenance & Repairs", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7310", "Janitorial Services", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7320", "Lawn & Grounds", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7400", "Insurance - Property & Liability", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7500", "Technology - Software & Subscriptions", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # Administration (8000)
    add("8100", "Office Supplies", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8200", "Legal & Audit", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8300", "Denominational Apportionment - Conference", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8310", "Denominational Apportionment - District", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8400", "Stewardship & Fundraising", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # Capital (9000)
    add("9100", "Depreciation Expense", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("9200", "Capital Expenditures - Building", "Asset", "BLDG", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("9210", "Capital Expenditures - Equipment", "Asset", "BLDG", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("9300", "Loan Principal", "Liability", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    schedules = [
        AllocationSchedule(
            schedule_id="UTIL_BY_SQFT",
            name="Utilities - Square Footage Allocation",
            basis="square_footage",
            allocations=[
                {"fund_id": "GEN", "pct": 75.0, "ministry_area": "FACILITIES"},
                {"fund_id": "GEN", "pct": 15.0, "ministry_area": "CHILDREN"},
                {"fund_id": "GEN", "pct": 10.0, "ministry_area": "YOUTH"},
            ],
            applies_to_categories=["UTILITIES"],
        ),
    ]

    apportionments = [
        ApportionmentAccount(account_number="8300", pct_of_revenue=Decimal("12.0")),
        ApportionmentAccount(account_number="8310", pct_of_revenue=Decimal("3.0")),
    ]

    return AccountingContext(
        church_id="grace_umc",
        church_name="Grace United Methodist Church",
        denomination_type=DenominationType.UMC,
        fiscal_year=2026,
        fiscal_year_start=date(2026, 1, 1),
        accounts=accounts,
        funds=funds,
        allocation_schedules=schedules,
        capitalisation_threshold_usd=Decimal("2500"),
        parsonage_allowance_current_year=Decimal("36000"),
        parsonage_allowance_used_ytd=Decimal("18500"),
        apportionment_accounts=apportionments,
    )


def seed_holy_comforter() -> AccountingContext:
    """Build the Holy Comforter Episcopal Church profile.

    Realistic Episcopal parish COA exercising:
      * Diocesan Assessment (apportionment, ~12.5% of NOI - placeholder)
      * Church Pension Fund (CPF) mandatory 18% clergy contribution
      * Rector's Discretionary Fund (BOARD_DESIGNATED, IRS-substantiated)
      * Permanently restricted endowment (UPMIFA) with separate principal/income
      * Parochial Report clergy compensation split (Schedule A)

    Persisted as backend/data/context_holy_comforter.json and indexed
    automatically into ChromaDB collection coa_holy_comforter.
    """
    funds = [
        Fund(fund_id="GEN", fund_name="General Operating",
             restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
             fund_category=FundCategory.GENERAL_OPERATING,
             purpose_description="Plate, pledge, and unrestricted gifts; "
                                  "pays clergy comp, CPF, diocesan assessment",
             expenditure_rules="Unrestricted - any operating expense",
             current_balance=Decimal("125000")),
        Fund(fund_id="OUTREACH", fund_name="Outreach & Mission",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
             fund_category=FundCategory.TEMP_RESTRICTED_PURPOSE,
             purpose_description="Designated outreach gifts; pass-through to "
                                  "ERD and partner agencies",
             expenditure_rules="Pass-through only to qualifying outreach "
                                "organizations (ERD, diocesan outreach)",
             current_balance=Decimal("18500")),
        Fund(fund_id="MEMORIAL", fund_name="Memorial Gifts",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
             fund_category=FundCategory.TEMP_RESTRICTED_PURPOSE,
             purpose_description="Donor-purposed gifts (altar flowers, music, "
                                  "sanctuary improvements)",
             expenditure_rules="Spend per donor's stated purpose; vestry "
                                "tracks intent on each gift",
             current_balance=Decimal("7200")),
        Fund(fund_id="RECTOR_DISC", fund_name="Rector's Discretionary Fund",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
             fund_category=FundCategory.BOARD_DESIGNATED,
             purpose_description="TEC Canon I.7 fund for charitable aid; "
                                  "rector sole signatory",
             expenditure_rules="IRS-substantiated charitable disbursements "
                                "only; never personal use of rector",
             current_balance=Decimal("3850")),
        Fund(fund_id="ENDOW_PRIN", fund_name="Endowment - Principal",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PERMANENT,
             fund_category=FundCategory.PERMANENTLY_RESTRICTED,
             purpose_description="Corpus preserved in perpetuity per UPMIFA",
             expenditure_rules="Principal never spent; only income may be "
                                "drawn (see ENDOW_INC)",
             current_balance=Decimal("450000")),
        Fund(fund_id="ENDOW_INC", fund_name="Endowment - Income",
             restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
             fund_category=FundCategory.TEMP_RESTRICTED_PURPOSE,
             purpose_description="Spendable income from endowment "
                                  "(typ. 4-5% rolling-average draw)",
             expenditure_rules="Distributed per vestry-approved spending "
                                "policy; supports parish operations",
             current_balance=Decimal("21000")),
    ]

    accounts: List[Account] = []

    def add(num: str, name: str, atype: str, fund: str, rc: RestrictionClass) -> None:
        accounts.append(Account(account_number=num, account_name=name, account_type=atype,
                                fund_id=fund, restriction_class=rc))

    # ----- Assets (1000s) -----
    add("1010", "Operating Cash", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1020", "Outreach Cash", "Asset", "OUTREACH", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("1030", "Memorial Cash", "Asset", "MEMORIAL", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("1040", "Rector's Discretionary Cash", "Asset", "RECTOR_DISC", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("1100", "Pledges Receivable", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1500", "Land", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1510", "Church Buildings", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1520", "Parish Hall", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1530", "Rectory", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1540", "Organ & Liturgical Equipment", "Asset", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("1900", "Endowment Investments - Principal", "Asset", "ENDOW_PRIN", RestrictionClass.WITH_RESTRICTION_PERMANENT)
    add("1910", "Endowment Investments - Accumulated Income", "Asset", "ENDOW_INC", RestrictionClass.WITH_RESTRICTION_PURPOSE)

    # ----- Liabilities (2000s) -----
    add("2010", "Accounts Payable", "Liability", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("2020", "Pass-Through Outreach Liability", "Liability", "OUTREACH", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("2030", "Payroll Liabilities", "Liability", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("2040", "CPF Payable", "Liability", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("2050", "Diocesan Assessment Payable", "Liability", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # ----- Net Assets (3000s) -----
    add("3100", "Net Assets - Without Restriction", "Equity", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("3200", "Net Assets - Purpose Restricted", "Equity", "OUTREACH", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("3300", "Net Assets - Endowment Principal", "Equity", "ENDOW_PRIN", RestrictionClass.WITH_RESTRICTION_PERMANENT)
    add("3310", "Net Assets - Endowment Income", "Equity", "ENDOW_INC", RestrictionClass.WITH_RESTRICTION_PURPOSE)

    # ----- Revenue (4000s) -----
    add("4100", "Pledge Income", "Revenue", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("4110", "Plate Offerings", "Revenue", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("4120", "Loose Plate / Visitor Offerings", "Revenue", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("4200", "Designated Gifts - Outreach", "Revenue", "OUTREACH", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("4210", "Designated Gifts - Memorial", "Revenue", "MEMORIAL", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("4300", "Endowment Income Distributions", "Revenue", "ENDOW_INC", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("4400", "Investment Income", "Revenue", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("4500", "Facility Use / Wedding Fees", "Revenue", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("4900", "Rector's Discretionary Contributions", "Revenue", "RECTOR_DISC", RestrictionClass.WITH_RESTRICTION_PURPOSE)

    # ----- Personnel - Parochial Report split (5000s) -----
    add("5100", "Clergy Salary (Rector)", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5101", "Clergy Housing Allowance", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5102", "Clergy SECA Reimbursement", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5103", "Clergy Continuing Education", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5104", "Clergy Travel & Auto", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5210", "CPF Pension Assessment (18%)", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5220", "Clergy Healthcare Premium", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5221", "Clergy Dental & Vision", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5222", "Clergy Life & Disability", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5300", "Lay Staff Wages - Parish Administrator", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5310", "Lay Staff Wages - Music Director", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5320", "Lay Staff Wages - Sexton", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5400", "Lay Staff Benefits - Health", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5410", "Lay Staff Benefits - Retirement (DTL)", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("5420", "Payroll Taxes (Employer FICA)", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # ----- Ministry (6000s) -----
    add("6100", "Worship - Music & Choir", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6110", "Altar Guild & Communion Supplies", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6120", "Liturgical Vestments & Linens", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6200", "Christian Formation - Children", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6210", "Christian Formation - Youth (EYC)", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6220", "Christian Formation - Adult", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6300", "Pastoral Care & Visitation", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("6400", "Outreach - Pass-Through Disbursements", "Expense", "OUTREACH", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("6410", "Episcopal Relief & Development (ERD)", "Expense", "OUTREACH", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("6500", "Memorial Designated Disbursements", "Expense", "MEMORIAL", RestrictionClass.WITH_RESTRICTION_PURPOSE)
    add("6900", "Rector's Discretionary Disbursements", "Expense", "RECTOR_DISC", RestrictionClass.WITH_RESTRICTION_PURPOSE)

    # ----- Facility (7000s) -----
    add("7100", "Mortgage / Rent", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7200", "Utilities - Electric", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7210", "Utilities - Gas", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7220", "Utilities - Water/Sewer", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7230", "Utilities - Internet/Phone", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7300", "Maintenance & Repairs", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7310", "Janitorial / Sexton Supplies", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7320", "Grounds & Landscaping", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7400", "Insurance - Property & Liability", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7410", "Insurance - Workers Comp", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("7500", "Technology & Software", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # ----- Administration (8000s) -----
    add("8100", "Office Supplies", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8200", "Legal & Audit", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8300", "Bank Fees & Merchant Processing", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8400", "Stewardship Campaign", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8410", "Diocesan Assessment", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)
    add("8420", "National Church / Province Pledge", "Expense", "GEN", RestrictionClass.WITHOUT_RESTRICTION)

    # ----- CPF allocation schedule (informational) -----
    schedules = [
        AllocationSchedule(
            schedule_id="CPF_18PCT",
            name="Church Pension Fund - 18% Clergy Assessment",
            basis="pct_of_clergy_comp",
            allocations=[
                # Source accounts that compose the assessment base
                {"source_account": "5100", "include_pct": 100.0,
                 "note": "Clergy salary - assessable base"},
                {"source_account": "5101", "include_pct": 100.0,
                 "note": "Clergy housing allowance - assessable base"},
                {"source_account": "5102", "include_pct": 100.0,
                 "note": "Clergy SECA reimbursement - assessable base"},
                # Target: 18% of base posts to expense 5210, credits liability 2040
                {"target_expense_account": "5210",
                 "target_liability_account": "2040",
                 "rate_pct": 18.0,
                 "note": "Mandatory CPF assessment per General Convention"},
            ],
            applies_to_categories=["CLERGY_COMPENSATION", "CLERGY_HOUSING",
                                    "SECA_REIMBURSEMENT"],
        ),
    ]

    # ----- Diocesan Assessment apportionment (12.5% placeholder) -----
    apportionments = [
        ApportionmentAccount(account_number="8410", pct_of_revenue=Decimal("12.5")),
    ]

    return AccountingContext(
        church_id="holy_comforter",
        church_name="Church of the Holy Comforter",
        denomination_type=DenominationType.EPISCOPAL,
        fiscal_year=2026,
        fiscal_year_start=date(2026, 1, 1),
        accounts=accounts,
        funds=funds,
        allocation_schedules=schedules,
        capitalisation_threshold_usd=Decimal("2500"),
        parsonage_allowance_current_year=Decimal("42000"),
        parsonage_allowance_used_ytd=Decimal("0"),
        apportionment_accounts=apportionments,
        warnings=[
            "Diocesan assessment rate (12.5%) is a planning placeholder - "
            "confirm with diocese for actual rate and base definition (NOI).",
            "CPF allocation schedule (CPF_18PCT) is informational; "
            "gl_mapper integration of basis='pct_of_clergy_comp' pending.",
        ],
    )


def ensure_seed() -> None:
    """Idempotent seed for first launch."""
    if not _ctx_path("grace_umc").exists():
        save_accounting_context(seed_sample_church())
    if not _ctx_path("holy_comforter").exists():
        save_accounting_context(seed_holy_comforter())
