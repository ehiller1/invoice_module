# EIME Architecture Handoff: Budget Feature Integration
Updated: 2026-05-06

## Project Summary

EIME (Embark Invoice Mapping Engine) is a FastAPI + CrewAI multi-agent system for church invoice processing. It extracts line items from PDF invoices, classifies expenses, maps them to GL accounts in a Chart of Accounts, runs risk/fraud assessment, optionally routes to human review (HITL), and emits a balanced journal entry. Churches are served as separate tenants; each church has a JSON context file on disk and a ChromaDB embedding collection.

**Stack:** Python 3.11, FastAPI, CrewAI, ChromaDB, Pydantic v2, pandas, pydantic-ai (Anthropic SDK), Tailwind CSS frontend (vanilla HTML/JS).

---

## 1. Current Invoice Processing Flow

```
POST /api/invoice/upload
  └── flow.create_job()          → ProcessingJob{status=UPLOADED} in _jobs dict
  └── background_tasks.run_pipeline(job_id)
          │
          ▼
  [Step 1] EXTRACTING
    tools/pdf_extractor.extract_invoice()
    → InvoiceDocument{vendor_name, invoice_number, total_amount, line_items[]}
          │
  [Step 2] COA load (no status change)
    tools/coa_store.load_accounting_context(church_id)
    → AccountingContext{accounts[], funds[], allocation_schedules[], ...}
    ERROR if COA not configured
          │
  [Step 3] CLASSIFYING
    tools/classifier.classify_line_items()
    tools/denomination_rules.apply_denomination_rules()
    → ClassifiedLineItem[]{expense_category, ministry_area, fund_eligibility,
                            flags{requires_hitl, capitalise, is_housing_related,
                                  is_missions_passthrough}, confidence}
          │
  [Step 4] Risk assessment (still CLASSIFYING status)
    tools/gl_mapper.map_line_items()        → DraftAllocations (placeholder)
    tools/risk_assessor.assess_risk()       → RiskAssessment{risk_level, risk_score,
                                                per_line_risks[], recommendations[]}
          │
  [Step 5] Fraud assessment (still CLASSIFYING status)
    tools/fraud_detector.assess_fraud()    → FraudAssessment{fraud_level, fraud_score,
                                                signals[], recommended_action}
    ┌── if fraud_level == CRITICAL:
    │     → status = PENDING_HITL  [EARLY EXIT — no GL mapping yet]
    │
  [Step 6] MAPPING
    DraftAllocations already computed in Step 4 (reused)
    → DraftAllocations{lines[{line_id, postings[{account_number, fund_id,
                              debit_amount, credit_amount, confidence}]}]}
          │
  [Step 7] REVIEWING
    tools/reviewer.review_allocations()
    → ReviewedAllocations{lines[{verdict: APPROVED|REVISE|ESCALATE}],
                           overall_verdict, escalation_items[], revision_items[]}

    Escalation triggers:
      - missions pass-through (requires attestation)
      - restricted fund purpose mismatch
      - unbalanced line
      - posting confidence < 0.85
      - housing allowance over-budget
      - capitalisation flag
      - classifier requires_hitl flag
      - risk CRITICAL line ids merged in from Step 4

  ┌── if escalation_items not empty:
  │     → status = PENDING_HITL  [GATE — waits for POST /api/jobs/{id}/hitl]
  │
  │   POST /api/jobs/{job_id}/hitl
  │     body: {line_decisions: [{line_id, action: APPROVED|OVERRIDE|REJECT,
  │                              notes, reviewer_id, missions_attestation}]}
  │     → flow.submit_hitl_decisions()
  │
  [Steps 9-10] BUILDING_ENTRY → EMITTED
    tools/journal_builder.build_journal_entry()
    → JournalEntry{entry_id, lines[{account_number, fund_id, debit, credit}],
                   total_debits, total_credits, balanced, status: DRAFT|PENDING_APPROVAL}
    status = EMITTED on job
```

### Key observation on storage

Jobs live in `flow._jobs: Dict[str, ProcessingJob]` — an in-memory dict. **There is no database.** All data is lost on server restart. The church context (COA, funds) persists to JSON files, but journal entries do not.

---

## 2. Data Models (backend/models/schemas.py)

### ProcessingJob (the central carrier object)
```python
ProcessingJob:
  job_id: str
  church_id: str
  filename: str
  pdf_path: str
  document_type: DocumentType
  status: ProcessingStatus   # UPLOADED → EXTRACTING → CLASSIFYING → MAPPING →
                              # REVIEWING → PENDING_HITL → BUILDING_ENTRY → EMITTED
  invoice_document: InvoiceDocument | None
  accounting_context: AccountingContext | None
  classified_items: ClassifiedLineItem[] | None
  draft_allocations: DraftAllocations | None
  reviewed_allocations: ReviewedAllocations | None
  hitl_decisions: HITLDecisions | None
  journal_entry: JournalEntry | None
  risk_assessment: Dict | None      # serialized RiskAssessment
  fraud_assessment: Dict | None     # serialized FraudAssessment
  audit_log: List[Dict]
```

### AccountingContext (church profile — persisted to JSON)
```python
AccountingContext:
  church_id: str
  church_name: str
  denomination_type: DenominationType
  fiscal_year: int
  fiscal_year_start: date
  accounts: Account[]              # GL accounts (73 for Holy Comforter)
  funds: Fund[]                    # Fund definitions (6 for Holy Comforter)
  allocation_schedules: AllocationSchedule[]
  capitalisation_threshold_usd: Decimal
  parsonage_allowance_current_year: Decimal
  parsonage_allowance_used_ytd: Decimal
  apportionment_accounts: ApportionmentAccount[]
  warnings: List[str]
  # MISSING: budget data — no budget field exists
```

### JournalEntry (the output)
```python
JournalEntry:
  entry_id: str
  church_id: str
  fiscal_year: int
  accounting_period: str       # "YYYY-MM"
  entry_date: date
  reference: str               # invoice_number
  vendor_name: str
  status: JEStatus             # DRAFT | PENDING_APPROVAL | APPROVED
  lines: JournalEntryLine[]
  total_debits: Decimal
  total_credits: Decimal
  balanced: bool
```

### Fund (relevant for budget)
```python
Fund:
  fund_id: str
  fund_name: str
  restriction_class: RestrictionClass
  fund_category: FundCategory
  purpose_description: str | None
  expenditure_rules: str | None
  current_balance: Decimal     # always 0 in current data — not tracked
  # MISSING: annual_budget, budget_periods, ytd_actual
```

### Account (relevant for budget)
```python
Account:
  account_number: str
  account_name: str
  account_type: str            # Asset | Liability | Revenue | Expense
  fund_id: str
  restriction_class: RestrictionClass
  active: bool
  # MISSING: annual_budget, ytd_actual, monthly_budget
```

---

## 3. Agent Architecture

EIME has **6 named agent archetypes** in `backend/agents/crews.py`. The agents are CrewAI shells; all domain expertise lives in SKILL.md files loaded from the skill registry at runtime.

| Agent | Role | Used For |
|---|---|---|
| Orchestrator | Invoice Processing Orchestrator | Discovers skills, emits execution plan JSON |
| Researcher | Accounting Context Researcher | Loads COA, funds, denomination rules |
| Worker | Invoice Processing Worker | PDF extraction, classification, GL mapping, JE drafting |
| Reviewer | Allocation Quality Reviewer | Validates fund restrictions, GAAP ASC 958 |
| Conversationalist | HITL Gate Coordinator | Surfaces escalated items to human reviewer |
| Membrane | Accounting Domain Distiller | Packages JournalEntry as AccountingDomainEvent |

### Current crew wiring

Only two crews are actually instantiated:
- `make_orchestrator_crew(pdf_path, church_id, document_type)` — planning only
- `make_researcher_crew(church_id, fiscal_year)` — COA loading summary

**Important:** The main pipeline in `flow.py` does NOT use CrewAI crews. It calls the tool functions directly (pdf_extractor, classifier, gl_mapper, reviewer, journal_builder). The CrewAI crews exist but are not invoked by `run_pipeline()`. The agents are effectively unused in production flow — the pipeline is a direct Python function chain.

### Where a budget agent would fit

```
[After Step 7: REVIEWING]
     ↓
[NEW Step 7b: BUDGET CHECK]
  budget_comparator.compare_to_budget(draft_allocations, ctx)
  → BudgetCheck{lines[{line_id, account_number, fund_id,
                        annual_budget, ytd_actual, this_invoice,
                        projected_annual, variance_pct,
                        status: WITHIN|WARNING|OVER}],
                overall_status, alerts[]}

  If overall_status == OVER_BUDGET:
    → add lines to reviewed.escalation_items (triggers HITL gate)
    → add budget context to HITL review card
  If overall_status == WARNING:
    → add to audit_log only (informational)
```

This requires:
1. Budget data on `AccountingContext` (or a separate budget store)
2. YTD actuals (either tracked in-memory or summed from emitted journal entries)
3. A new tool `tools/budget_comparator.py`
4. A new agent archetype `make_budget_analyst()` in crews.py (optional — could be just a tool)

---

## 4. File Storage

### Church context files (VERIFIED)
- Path pattern: `backend/data/context_{church_id}.json`
- Format: `AccountingContext.model_dump_json(indent=2)`
- Loaded/saved via `coa_store.load_accounting_context()` / `coa_store.save_accounting_context()`
- Examples: `context_holy_comforter.json`, `context_grace_umc.json`, `context_test_presbyterian.json`

### Where to add budget data

Option A — Extend AccountingContext JSON (simplest):
```json
{
  "church_id": "holy_comforter",
  ...existing fields...,
  "budget": {
    "fiscal_year": 2026,
    "accounts": {
      "7100": {"annual": 24000, "periods": [2000, 2000, 2000, ...]},
      "7200": {"annual": 18000, "periods": [1500, 1500, ...]}
    },
    "funds": {
      "GEN": {"annual": 450000}
    },
    "uploaded_at": "2026-01-15T10:00:00"
  }
}
```
This requires adding a `budget: Optional[BudgetPlan]` field to `AccountingContext`.

Option B — Separate budget file:
- Path: `backend/data/budget_{church_id}_{fiscal_year}.json`
- Loaded independently in the pipeline

Option A is recommended — budget is tightly coupled to fiscal_year and COA.

### YTD actuals tracking

Currently zero infrastructure for this. Options:
1. Sum emitted journal entries at runtime (requires journal entries to survive restart — needs SQLite/Postgres)
2. Store a running YTD tally per account in `AccountingContext` (simpler, survives as JSON)
3. Accept that budget check uses only "this invoice" as the unit (no cross-invoice YTD)

Option 2 recommended for MVP: add `ytd_actuals: Dict[str, Decimal]` (account_number → amount) to `AccountingContext`. Update after each EMITTED journal entry.

---

## 5. Spreadsheet Parser Capabilities (VERIFIED)

`backend/tools/spreadsheet_parser.py` already handles:
- Excel (.xlsx, .xls) and CSV
- Multi-sheet Excel (auto-detects accounts vs. funds by column names)
- Column name normalization (lowercase, underscore)
- Column aliases (account_number/number/code, account_name/name/description, etc.)
- Returns `{"accounts": [...], "funds": [...]}`

**Can be extended for budget spreadsheets.** Budget format would be a new sheet type detected by column presence of "budget" or "annual_budget":

```
Columns: account_number | account_name | annual_budget | jan | feb | mar | ... | dec
```

Proposed extension — add to `parse_spreadsheet()`:
```python
has_budget_cols = any(col in df.columns for col in ["annual_budget", "budget", "budgeted"])
if has_budget_cols:
    result["budget"] = _extract_budget_from_df(df)
```

A new endpoint `POST /api/churches/{church_id}/budget/import-spreadsheet` would mirror `import_coa_spreadsheet`.

---

## 6. UI Integration Points

### Current pages
- `/` (index.html) — Invoice upload, pipeline progress tracking, result summary
- `/jobs.html` — Job list, risk/fraud badges, expandable detail with journal entry table, HITL modal
- `/coa.html` — Chart of accounts editor (accounts + funds CRUD, spreadsheet import)
- `/skills.html` — Skill library browser
- `/chat.html` — Agent Q&A interface

### HITL review modal (jobs.html) — key integration point
The modal at `openHITL()` already:
- Shows each escalated line with description, amount, expense_category
- Shows escalation reasons in a list
- Provides Approve/Override/Reject buttons
- Supports missions attestation checkbox
- Submits via `POST /api/jobs/{job_id}/hitl`

**Budget alerts can be injected here** by adding budget variance context to the escalation reasons string, which is already rendered in the modal's amber box.

### Where to display budget vs. actual
1. **Job detail panel** (expandable section in jobs.html) — add a "Budget Variance" section alongside the existing "Risk & Fraud Assessment" section. Pattern is already established.

2. **HITL modal** — if budget OVER triggers escalation, include variance amounts in the escalation reason text. The modal renders `reasons[]` as a list — budget info goes there naturally.

3. **New Budget page** — `/budget.html` for uploading budget spreadsheets and viewing YTD actual vs. budget by account/fund. This is a standalone management view.

### How recommendations are currently shown
- Risk recommendations: `r.recommendations[]` rendered as `→ rec` text in the risk panel div
- Fraud recommended_action: shown as colored text (green/amber/orange/red) based on action string
- Reviewer reasons: rendered as `<li>` items in the HITL modal amber box

**Budget recommendations follow the same pattern** — a `budget_recommendation` string on each flagged line, displayed in the same HITL modal or job detail panel.

---

## 7. Data Model Gaps for Budget Feature

| Gap | Description | Fix |
|---|---|---|
| No budget field on AccountingContext | No `budget` or `annual_budget` on Account or AccountingContext | Add `BudgetPlan` model + optional field |
| No YTD actuals | Journal entries not persisted; no running totals | Add `ytd_actuals: Dict[str, Decimal]` to AccountingContext; update after EMITTED |
| No budget endpoint | No API to upload/query budget | Add `POST /budget/import-spreadsheet`, `GET /budget`, `PUT /budget` |
| No BudgetCheck schema | No Pydantic model for budget comparison result | Add to schemas.py |
| No budget comparator tool | No tool in tools/ to do comparison | Add `tools/budget_comparator.py` |
| No budget agent | No CrewAI agent for budget analysis | Add `make_budget_analyst()` to crews.py (optional) |
| No UI for budget | No page to manage/view budgets | Add `/budget.html` |
| fund.current_balance always 0 | Fund balances not maintained | Update after each EMITTED JE |

---

## 8. Proposed New Schemas

```python
class BudgetPeriod(BaseModel):
    month: int           # 1-12
    amount: Decimal

class AccountBudget(BaseModel):
    account_number: str
    annual_budget: Decimal
    periods: List[BudgetPeriod] = Field(default_factory=list)

class BudgetPlan(BaseModel):
    fiscal_year: int
    accounts: List[AccountBudget] = Field(default_factory=list)
    uploaded_at: datetime
    uploaded_by: Optional[str] = None

class BudgetLineStatus(str, Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    WARNING = "WARNING"          # >80% of annual consumed
    OVER_BUDGET = "OVER_BUDGET"  # would exceed annual

class BudgetLineCheck(BaseModel):
    line_id: str
    account_number: str
    account_name: str
    fund_id: str
    annual_budget: Decimal
    ytd_actual: Decimal          # before this invoice
    this_invoice: Decimal        # amount this posting adds
    projected_ytd: Decimal       # ytd_actual + this_invoice
    remaining_budget: Decimal    # annual_budget - projected_ytd
    consumed_pct: float          # projected_ytd / annual_budget
    status: BudgetLineStatus
    recommendation: str

class BudgetCheck(BaseModel):
    overall_status: BudgetLineStatus
    lines: List[BudgetLineCheck]
    alerts: List[str] = Field(default_factory=list)
    checked_at: datetime
```

Add to `AccountingContext`:
```python
budget: Optional[BudgetPlan] = None
ytd_actuals: Dict[str, Decimal] = Field(default_factory=dict)
```

Add to `ProcessingJob`:
```python
budget_check: Optional[Dict[str, Any]] = None
```

---

## 9. Proposed Integration Sequence (Modified Pipeline)

```
run_pipeline(job_id):
  ... existing steps 1-7 (extract → classify → risk → fraud → map → review) ...

  # NEW: Step 7b — Budget comparison
  if ctx.budget is not None:
      budget_result = await run_in_executor(
          None, compare_to_budget, job.draft_allocations, ctx
      )
      job.budget_check = budget_result.to_dict()
      job.audit_log.append({...budget summary...})

      # Escalate over-budget lines to HITL
      for line_check in budget_result.lines:
          if line_check.status == BudgetLineStatus.OVER_BUDGET:
              if line_check.line_id not in reviewed.escalation_items:
                  reviewed.escalation_items.append(line_check.line_id)
                  # Augment the reviewed line's reasons
                  for rl in reviewed.lines:
                      if rl.line_id == line_check.line_id:
                          rl.reasons.append(line_check.recommendation)

  # Step 8: HITL gate (existing — now includes budget escalations)
  if reviewed.escalation_items:
      _update_job(job, ProcessingStatus.PENDING_HITL)
      return

  await _build_and_emit(job, reviewed, None)
```

After `_build_and_emit`, update YTD actuals:
```python
# After EMITTED, update ytd_actuals for future invoices
if ctx.budget is not None:
    for line in job.journal_entry.lines:
        if line.debit > 0:
            ctx.ytd_actuals[line.account_number] = (
                ctx.ytd_actuals.get(line.account_number, Decimal("0")) + line.debit
            )
    coa_store.save_accounting_context(ctx)
```

---

## 10. API Endpoints to Add

```
POST /api/churches/{church_id}/budget/import-spreadsheet
  body: multipart file (Excel with budget columns)
  action: parse → update ctx.budget → save_accounting_context

POST /api/churches/{church_id}/budget
  body: BudgetPlan JSON
  action: ctx.budget = plan → save_accounting_context

GET  /api/churches/{church_id}/budget
  returns: ctx.budget + ctx.ytd_actuals merged

GET  /api/churches/{church_id}/budget/variance
  returns: per-account budget vs. ytd_actual comparison table

DELETE /api/churches/{church_id}/budget
  action: ctx.budget = None → save_accounting_context
```

---

## 11. File Locations for New Code

```
backend/
  models/
    schemas.py              ← add BudgetPlan, AccountBudget, BudgetPeriod,
                               BudgetLineCheck, BudgetCheck, BudgetLineStatus
                               extend AccountingContext + ProcessingJob
  tools/
    budget_comparator.py    ← NEW: compare_to_budget(draft, ctx) → BudgetCheck
    spreadsheet_parser.py   ← extend: detect budget sheet, _extract_budget_from_df()
  main.py                   ← add budget endpoints (import, get, put, delete, variance)
  flow.py                   ← insert Step 7b after review_allocations()
                               insert YTD update after _build_and_emit()
  agents/
    crews.py                ← optionally add make_budget_analyst() agent

frontend/
  budget.html               ← NEW: budget upload UI + variance table
  jobs.html                 ← extend riskFraudPanel() to include budget check panel
                               extend HITL modal reasons to show budget context
  index.html                ← no changes needed
```

---

## 12. Constraints and Patterns to Follow

- All new Pydantic models use `BaseModel` from pydantic v2; use `Field(default_factory=...)` for mutable defaults
- New schemas go in `backend/models/schemas.py` alongside existing models
- New tools go in `backend/tools/` as standalone Python modules imported by `flow.py`
- The pipeline in `flow.py` calls tools directly (not via CrewAI) — follow this pattern for budget_comparator
- Church context mutations always go through `coa_store.save_accounting_context(ctx)` which also rebuilds the ChromaDB index
- Frontend uses Tailwind via CDN; vanilla JS with fetch(); pattern: `async function name() { const res = await fetch(...); ... }`
- UI color palette: navy-900/800/700 sidebar, gold-500 accent, slate-* body
- HITL modal: escalation reasons are a `string[]` appended to `reviewed.lines[].reasons` — budget reasons should follow this convention
- Spreadsheet columns: normalize to lowercase + underscores before checking presence

---

## 13. Agent Architecture Note for Budget Agent

If a budget agent is desired (rather than just a tool), the pattern from crews.py:

```python
def make_budget_analyst() -> Agent:
    return Agent(
        role="Budget Compliance Analyst",
        goal=(
            "Compare each invoice line item against the church's approved budget. "
            "Identify lines that would exceed annual or period allocations and "
            "produce a structured BudgetCheck with per-line variance and recommendations."
        ),
        backstory=(
            "You enforce fiscal discipline for church finance committees. "
            "All budget thresholds come from the church's uploaded BudgetPlan. "
            "You never approve an over-budget posting without Finance Committee sign-off."
        ),
        tools=[skill_load_tool],
        verbose=False,
        allow_delegation=False,
    )
```

The budget skill (SKILL.md) would define the comparison algorithm and escalation thresholds.

---

## Open Questions / Uncertainties

- INFERRED: `fund.current_balance` is declared but always 0 in data — confirm whether Embark ERP maintains fund balances externally, or whether EIME should track them
- INFERRED: YTD actuals would reset at fiscal_year_start — confirm whether `ytd_actuals` should be keyed by `{fiscal_year}:{account_number}` for multi-year support
- VERIFIED: No persistence layer exists — in-memory only. For budget YTD to survive restarts, it must be stored in the church JSON context file (Option 2 above)
- UNCERTAIN: Whether budget comparison should gate on fund-level totals (all accounts in GEN fund vs. GEN fund budget) or account-level only
- UNCERTAIN: What warning threshold to use (80%? configurable per church?)
- INFERRED: The spreadsheet parser sheet detection uses column presence — a budget sheet needs unique column names ("annual_budget", "jan", "feb", etc.) that won't collide with accounts/funds sheets
