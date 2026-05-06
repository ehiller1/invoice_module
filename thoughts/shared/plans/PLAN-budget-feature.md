# Implementation Plan: EIME Budget Upload, Comparison & Transaction Approval

Generated: 2026-05-06
Author: plan-agent
Source: ARCHITECTURE.md handoff (build-budget-feature)

---

## Executive Summary

### What We're Building

A budget plane on top of EIME's existing invoice pipeline that:

1. Lets churches upload an annual budget spreadsheet (account-keyed, monthly granularity)
2. Compares each invoice's draft GL postings against `annual_budget − ytd_actual` at Step 7b (after `review_allocations()`, before the HITL gate)
3. Escalates `OVER_BUDGET` lines to the human-in-the-loop modal as additional `escalation_items`, with variance numbers surfaced as `reasons[]` strings
4. Tracks `ytd_actuals` per account in `AccountingContext` JSON, updated only after a job reaches `EMITTED`
5. Exposes a Budget management page (`/budget.html`), variance reports, threshold configuration, and year-end reset

### Why This Approach

- **Deterministic, not agentic.** Budget arithmetic is `annual − ytd − this_invoice`. No LLM needed. Implemented as a plain Python tool (`tools/budget_comparator.py`) called directly from `flow.py`, mirroring how `risk_assessor` and `fraud_detector` are wired today.
- **Storage piggybacks on the existing JSON context.** EIME has no DB. Adding `budget: Optional[BudgetPlan]` and `ytd_actuals: Dict[str, Decimal]` to `AccountingContext` and persisting via `coa_store.save_accounting_context()` survives restart with zero new infrastructure.
- **HITL escalation reuses existing channels.** Over-budget lines are appended to `reviewed.escalation_items` and budget reasons are appended to `reviewed.lines[].reasons`, so the existing HITL modal renders them with no schema break.
- **Spreadsheet parser already discriminates sheets by column presence.** Adding a budget-sheet path (detected on `annual_budget` / `jan…dec` columns) is a small extension, not a rewrite.

### Out of Scope (intentionally)

- Multi-year budget history (only current `fiscal_year` retained)
- Fund-level budget enforcement (account-level only for v1)
- Budget *forecasting* / scenario modeling (just compare against frozen plan)
- Budget approval workflow (i.e. requiring board sign-off on the plan itself)
- Persisting journal entries to a database — YTD is still derived from the JSON context, not from re-summing JEs

---

## Existing Codebase Anchors

Verified from `ARCHITECTURE.md` and direct file inspection:

| Anchor | Location | Role |
|---|---|---|
| Pipeline orchestrator | `backend/flow.py` (237 lines) | Direct Python function chain — does NOT use CrewAI in production. Insert Step 7b here. |
| Pydantic models | `backend/models/schemas.py` (420 lines) | `AccountingContext` at line 195, `DraftAllocations` at line 257, `ReviewedLine.reasons` at line 270 |
| FastAPI routes | `backend/main.py` (563 lines) | Add 5 budget endpoints alongside `/import-spreadsheet` |
| Spreadsheet parser | `backend/tools/spreadsheet_parser.py` (240 lines) | Multi-sheet, column-alias-aware. Extend with budget sheet detection. |
| Context store | `backend/tools/coa_store.py` | `load_accounting_context()` / `save_accounting_context()` — single source of truth for persistence |
| HITL modal | `frontend/jobs.html` (441 lines) | Renders `reviewed.lines[].reasons` as `<li>` items in amber box. Budget reasons get free placement. |
| COA editor | `frontend/coa.html` (727 lines) | Pattern for file-upload + table-render + persist; mirror for `/budget.html`. |

---

## Pipeline Modification Diagram (Step 7b Insertion)

```
[Step 7] REVIEWING                          (existing)
  reviewer.review_allocations(draft, ctx)
  → ReviewedAllocations{lines, escalation_items, revision_items}
        │
        ▼
[Step 7b] BUDGET CHECK                      (NEW — only if ctx.budget is not None)
  budget_comparator.compare_to_budget(draft, ctx)
  → List[BudgetCheck]   one per posting line
        │
        ├── for each BudgetCheck where status == OVER_BUDGET:
        │     - if line_id not in reviewed.escalation_items: append it
        │     - append BudgetCheck.reason to the matching reviewed.lines[i].reasons[]
        │
        ├── for each BudgetCheck where status == WARNING:
        │     - append "WARNING: …" to reviewed.lines[i].reasons[] (informational)
        │     - DO NOT modify escalation_items
        │
        └── always: job.budget_check = [...]  (for UI rendering)
                    job.audit_log.append({"step":"budget_check", "summary":...})
        │
        ▼
[Step 8] HITL gate                          (existing — now sees union of GAAP + budget escalations)
  if reviewed.escalation_items: status = PENDING_HITL ; return
        │
        ▼
[Step 9-10] BUILDING_ENTRY → EMITTED        (existing)
  journal_builder.build_journal_entry()
        │
        ▼
[NEW: post-emit YTD update]                 (NEW)
  for each line in journal_entry.lines:
    if line.debit > 0:
      ctx.ytd_actuals[line.account_number] += line.debit
  coa_store.save_accounting_context(ctx)
```

**Critical invariant:** YTD is mutated only on EMITTED. Rejected/cancelled jobs do NOT touch `ytd_actuals`. Approved-via-HITL OVER_BUDGET jobs DO update YTD (because they reach EMITTED).

---

## Data Model Changes

### New Pydantic models (`backend/models/schemas.py`)

```python
class BudgetMonth(BaseModel):
    """Monthly budget allocation for a single account.
    All 12 months always present; missing months in upload fill with 0.
    """
    jan: Decimal = Decimal("0")
    feb: Decimal = Decimal("0")
    mar: Decimal = Decimal("0")
    apr: Decimal = Decimal("0")
    may: Decimal = Decimal("0")
    jun: Decimal = Decimal("0")
    jul: Decimal = Decimal("0")
    aug: Decimal = Decimal("0")
    sep: Decimal = Decimal("0")
    oct: Decimal = Decimal("0")
    nov: Decimal = Decimal("0")
    dec: Decimal = Decimal("0")
    annual_total: Decimal = Decimal("0")  # canonical figure for compare


class BudgetPlan(BaseModel):
    fiscal_year: int
    plan_date: date                              # date plan was approved
    amendment_number: int = 0                    # 0 = original, 1+ = amendments
    accounts: Dict[str, BudgetMonth] = Field(default_factory=dict)
                                                 # key = account_number
    uploaded_at: datetime
    uploaded_by: Optional[str] = None
    source_filename: Optional[str] = None


class BudgetStatus(str, Enum):
    NO_BUDGET = "NO_BUDGET"            # account has no budget entry — skip
    WITHIN_BUDGET = "WITHIN_BUDGET"    # projected_ytd <= warning_threshold * annual
    WARNING = "WARNING"                # warning_threshold * annual < projected_ytd <= annual
    OVER_BUDGET = "OVER_BUDGET"        # projected_ytd > annual


class BudgetCheck(BaseModel):
    line_id: str
    account_number: str
    account_name: str
    fund_id: str
    annual_budget: Decimal
    ytd_actual: Decimal              # before this invoice
    this_invoice: Decimal            # debit amount this posting adds
    after: Decimal                   # ytd_actual + this_invoice
    remaining: Decimal               # annual_budget - after
    consumed_pct: float              # after / annual_budget (0.0–∞)
    status: BudgetStatus
    reason: str                      # human-readable, injected to reasons[]
```

### Updates to existing models

```python
# AccountingContext (schemas.py line 195)
class AccountingContext(BaseModel):
    # …existing fields…
    budget: Optional[BudgetPlan] = None
    ytd_actuals: Dict[str, Decimal] = Field(default_factory=dict)
                                                 # key = account_number, value = YTD debits
    budget_warning_threshold: float = 0.80       # 80% default; configurable per church


# ProcessingJob
class ProcessingJob(BaseModel):
    # …existing fields…
    budget_check: Optional[List[BudgetCheck]] = None
```

**Backward compatibility:** All new fields have defaults. Existing `context_*.json` files load unchanged; budget logic is skipped when `budget is None`.

---

## API Specification

### Upload budget spreadsheet
```
POST /api/churches/{church_id}/budget/import-spreadsheet
Content-Type: multipart/form-data
Body: file (.xlsx | .xls | .csv)

200 OK
{
  "fiscal_year": 2026,
  "accounts_loaded": 73,
  "annual_total": "452000.00",
  "warnings": ["account 9999 in budget not in COA — skipped"]
}
422  if no budget-shaped sheet detected, or all account_numbers unknown
```

### Get current budget plan + YTD
```
GET /api/churches/{church_id}/budget

200 OK
{
  "budget": {
    "fiscal_year": 2026,
    "plan_date": "2026-01-15",
    "amendment_number": 0,
    "accounts": { "7100": {"jan": 2000, …, "annual_total": 24000}, … },
    "uploaded_at": "...",
    "source_filename": "fy26-budget.xlsx"
  },
  "ytd_actuals": { "7100": "8400.00", "7200": "1200.00" },
  "budget_warning_threshold": 0.80
}
404  if budget not configured
```

### Variance report
```
GET /api/churches/{church_id}/budget/variance-report

200 OK
{
  "fiscal_year": 2026,
  "as_of": "2026-05-06T..",
  "totals": {
    "annual_budget": "452000.00",
    "ytd_actual":    "118400.00",
    "remaining":     "333600.00",
    "consumed_pct":  0.262
  },
  "buckets": {
    "within":   [ {account_number, account_name, annual, ytd, remaining, pct}, … ],
    "at_risk":  [ … ],   # 80% <= pct < 100%
    "over":     [ … ]
  }
}
```

### Year-end reset / amendment
```
PUT /api/churches/{church_id}/budget/ytd-reset
Body: { "confirm": true, "reset_to_zero": true }
200 OK { "previous_ytd_total": "118400.00", "reset_at": "..." }

POST /api/churches/{church_id}/budget/year-end-reset
Body: { "next_fiscal_year": 2027, "roll_forward_plan": false, "confirm": true }
200 OK — resets ytd_actuals, optionally retains BudgetPlan for next year
```

### Threshold configuration
```
PUT /api/churches/{church_id}/budget-warning-threshold
Body: { "threshold": 0.85 }      # 0.0 … 1.0
200 OK { "budget_warning_threshold": 0.85 }
422  if outside [0,1]
```

---

## Implementation Tasks

Each task below is independently testable. Order matters: tasks 1–5 form the backend backbone; 6–7 the API/UI frontends; 8–11 polish and integration; 12–13 tests and docs.

---

### Task 1 — Add Budget Pydantic Schemas

**Files:** `backend/models/schemas.py`

**Description:** Add `BudgetMonth`, `BudgetPlan`, `BudgetStatus` enum, `BudgetCheck`. Extend `AccountingContext` with `budget`, `ytd_actuals`, `budget_warning_threshold`. Extend `ProcessingJob` with `budget_check`.

**Inputs:** none (pure schema work)
**Outputs:** new symbols importable from `backend.models.schemas`
**Dependencies:** none — must land first
**Validation:**
- `pytest -k budget_schema` — round-trip JSON serialization
- Loading `context_holy_comforter.json` (which has no budget field) must still succeed
- `BudgetPlan(fiscal_year=2026, plan_date=date.today(), accounts={"7100": BudgetMonth(annual_total=Decimal("24000"))}, uploaded_at=datetime.utcnow()).model_dump_json()` round-trips

---

### Task 2 — Extend Spreadsheet Parser for Budget Sheets

**Files:** `backend/tools/spreadsheet_parser.py`

**Description:** Add `_extract_budget_from_df(df) -> Dict[str, BudgetMonth]` and detect budget sheets in `parse_spreadsheet()` using column-presence heuristic.

Detection rule (any of):
- `annual_budget` column AND `account_number` (or alias) column → "annual-only" form
- `account_number` (or alias) AND any of `jan|feb|…|dec` → "monthly" form
- Both → use monthly columns; reconcile against annual if present

Result shape: `result["budget"] = {"accounts": {account_number: BudgetMonth, …}, "annual_total": Decimal}`.

Missing month columns → fill with `Decimal("0")`. If both monthly + annual_total present and disagree by >$1, append warning to `result["warnings"]` and prefer the explicit `annual_total`.

**Inputs:** Excel/CSV file path
**Outputs:** parsed `{"accounts": [...], "funds": [...], "budget": {...}, "warnings": [...]}`
**Dependencies:** Task 1 (`BudgetMonth` schema)
**Validation:**
- Synthetic xlsx with columns `account_number, jan…dec` → 12 months populated, annual_total = sum
- CSV with only `account_number, annual_budget` → annual_total set, all months 0
- Mixed sheet (some accounts, some budget) → both keys populated
- Unknown columns ignored gracefully
- Tested with at least one real fixture xlsx

---

### Task 3 — Implement `compare_to_budget` Tool

**Files:** `backend/tools/budget_comparator.py` (NEW)

**Description:**
```python
def compare_to_budget(
    draft: DraftAllocations,
    ctx: AccountingContext,
) -> List[BudgetCheck]:
```

Algorithm:
1. If `ctx.budget is None`: return `[]`.
2. For each `line` in `draft.lines`, for each `posting` in `line.postings` with `posting.debit_amount > 0`:
   a. Look up `bm = ctx.budget.accounts.get(posting.account_number)`. If `None` → emit `BudgetCheck(status=NO_BUDGET, reason="No budget configured for this account")`.
   b. `annual = bm.annual_total`
   c. `ytd = ctx.ytd_actuals.get(posting.account_number, Decimal("0"))`
   d. `this_invoice = posting.debit_amount`
   e. `after = ytd + this_invoice`
   f. `remaining = annual - after`
   g. `consumed_pct = float(after / annual)` (guard `annual == 0` → treat as `OVER_BUDGET` if `this_invoice > 0`)
   h. Status:
      - `after > annual` → `OVER_BUDGET`
      - `after > ctx.budget_warning_threshold * annual` → `WARNING`
      - else → `WITHIN_BUDGET`
   i. Reason string follows templates:
      - OVER: `"OVER BUDGET: {acct_name} ({acct_no}) — projected ${after} exceeds annual ${annual} by ${after - annual} ({consumed_pct:.0%} consumed)"`
      - WARNING: `"WARNING: {acct_name} ({acct_no}) at {consumed_pct:.0%} of annual budget after this invoice"`
      - WITHIN: `"Within budget: {acct_name} — ${remaining} remaining of ${annual}"`
      - NO_BUDGET: `"No budget configured for account {acct_no}"`

**Inputs:** `DraftAllocations`, `AccountingContext`
**Outputs:** `List[BudgetCheck]` — one entry per debit posting (credit-only postings skipped)
**Dependencies:** Tasks 1
**Validation:**
- Unit tests cover within / warning / over / no_budget / annual_zero / multi-line
- Pure function; no I/O; deterministic; runs in <10 ms for 50 lines
- `Decimal` arithmetic throughout — no float drift

---

### Task 4 — Wire Budget Check into Pipeline (Step 7b)

**Files:** `backend/flow.py`

**Description:** After `reviewer.review_allocations()` and before the `if reviewed.escalation_items:` gate, insert:

```python
if ctx.budget is not None:
    budget_results = await asyncio.get_running_loop().run_in_executor(
        None, compare_to_budget, job.draft_allocations, ctx
    )
    job.budget_check = budget_results

    over = [b for b in budget_results if b.status == BudgetStatus.OVER_BUDGET]
    warn = [b for b in budget_results if b.status == BudgetStatus.WARNING]

    # Inject reasons into existing reviewed.lines (so HITL modal sees them)
    by_line: Dict[str, ReviewedLine] = {l.line_id: l for l in reviewed.lines}
    for b in budget_results:
        if b.status in (BudgetStatus.OVER_BUDGET, BudgetStatus.WARNING):
            rl = by_line.get(b.line_id)
            if rl is not None:
                rl.reasons.append(b.reason)

    # Escalate OVER lines (WARNING is informational only)
    for b in over:
        if b.line_id not in reviewed.escalation_items:
            reviewed.escalation_items.append(b.line_id)

    job.audit_log.append({
        "step": "budget_check",
        "over": len(over),
        "warning": len(warn),
        "total_lines_checked": len(budget_results),
        "timestamp": datetime.utcnow().isoformat(),
    })
```

**Inputs:** running `ProcessingJob` with `draft_allocations` + `reviewed_allocations` populated
**Outputs:** mutated `reviewed`, populated `job.budget_check`, audit log entry
**Dependencies:** Tasks 1, 3
**Validation:**
- E2E: run an invoice with 1 over-budget line through pipeline; confirm `status == PENDING_HITL` even when reviewer alone returned no escalations
- Confirm WARNING-only invoice still reaches EMITTED (warnings inform but do not gate)
- Confirm `ctx.budget is None` path is a no-op (existing behavior preserved)

---

### Task 5 — Update YTD Actuals After EMIT

**Files:** `backend/flow.py` (in `_build_and_emit` or its caller)

**Description:** After successful journal-entry build and `status = EMITTED`, before returning:

```python
if ctx.budget is not None and job.journal_entry is not None:
    for jl in job.journal_entry.lines:
        if jl.debit > 0:
            current = ctx.ytd_actuals.get(jl.account_number, Decimal("0"))
            ctx.ytd_actuals[jl.account_number] = current + jl.debit
    coa_store.save_accounting_context(ctx)
```

**Critical:** Does NOT run on REJECTED outcomes from HITL. The branch in `submit_hitl_decisions()` that aborts the job (all lines REJECT) must short-circuit before reaching `_build_and_emit`. Verify the existing flow already does this; if not, gate the YTD update on `job.status == EMITTED` explicitly.

**Inputs:** `JournalEntry`, mutable `AccountingContext`
**Outputs:** persisted updated context JSON file
**Dependencies:** Task 1 (ytd_actuals field)
**Validation:**
- Integration test: process two invoices for account 7100 ($500 each); after both EMITTED, `ctx.ytd_actuals["7100"] == Decimal("1000")`
- Reject HITL on second invoice; YTD remains at $500
- Concurrency note: file write is not locked. Document this; flag for future DB migration but accept for v1.

---

### Task 6 — Add Budget API Endpoints

**Files:** `backend/main.py`

**Description:** Add the 5 endpoints in the API spec above. Mirror the existing `import_coa_spreadsheet` handler for the upload route — same auth, same error shape, same pattern of reading file → calling parser → updating ctx → calling `save_accounting_context`.

For `GET /budget/variance-report`: compute live by iterating `ctx.budget.accounts` against `ctx.ytd_actuals`. No new persistent state.

For `PUT /budget/ytd-reset`: requires explicit `{ "confirm": true }`; reject otherwise with 400.

For `PUT /budget-warning-threshold`: validate `0.0 <= threshold <= 1.0`.

**Inputs:** HTTP requests
**Outputs:** JSON responses per spec
**Dependencies:** Tasks 1, 2 (parser must understand budget sheets)
**Validation:**
- `curl` round-trip for each endpoint against a running instance
- 422 on invalid spreadsheet (no budget columns)
- 404 on `GET` when no budget configured
- Threshold rejected at 1.5 and -0.1

---

### Task 7 — Build `/budget.html` Frontend Page

**Files:** `frontend/budget.html` (NEW)

**Description:** Standalone management page. Layout (matches `/coa.html` chrome — same sidebar, same Tailwind classes):

```
┌── Sidebar (navy-900) ──┬── Main ──────────────────────────────┐
│ • Invoices             │ Page header: "Budget — FY 2026"      │
│ • Jobs                 ├──────────────────────────────────────┤
│ • Chart of Accounts    │ ┌─ Upload card ─────────────────┐    │
│ • Budget         ←     │ │ Drop .xlsx here               │    │
│ • Skills               │ │ [Download Template] button    │    │
│ • Chat                 │ └───────────────────────────────┘    │
│                        │ ┌─ Threshold slider ────────────┐    │
│                        │ │ Warning at: [80%] ───●─── 100%│    │
│                        │ └───────────────────────────────┘    │
│                        │ ┌─ Variance summary cards (3) ──┐    │
│                        │ │ Within │ At Risk │ Over       │    │
│                        │ │   58   │    9    │  6         │    │
│                        │ └───────────────────────────────┘    │
│                        │ ┌─ Budget table ────────────────┐    │
│                        │ │ Acct # │ Name │ Annual │ YTD  │    │
│                        │ │        │      │        │ Used │    │
│                        │ │        │      │ progress bar  │    │
│                        │ └───────────────────────────────┘    │
└────────────────────────┴──────────────────────────────────────┘
```

JS contracts:
- `loadBudget()` → `GET /api/churches/{cid}/budget` → render rows
- `loadVariance()` → `GET .../variance-report` → render summary cards + bucket-color rows
- `uploadBudget(file)` → `POST .../budget/import-spreadsheet` → reload
- `setThreshold(v)` → `PUT .../budget-warning-threshold`
- `downloadTemplate()` → static link to `frontend/templates/budget-template.xlsx` (generated in Task 13)

Color bands per row using `consumed_pct`:
- `< threshold` → green (`bg-emerald-50`)
- `threshold ≤ pct < 1.0` → yellow (`bg-amber-50`)
- `>= 1.0` → red (`bg-rose-50`)

**Dependencies:** Task 6 (endpoints live)
**Validation:**
- Manual: upload a budget xlsx, see rows; adjust threshold, see color bands recompute; refresh page, state persists

---

### Task 8 — Extend HITL Modal with Budget Check Section

**Files:** `frontend/jobs.html`

**Description:** In `openHITL(jobId)`, fetch `/api/jobs/{id}` (which now includes `budget_check`). After the existing Risk/Fraud panel, append a Budget Check panel only if `job.budget_check?.length`:

```
┌─ Budget Check ────────────────────────────────────────────┐
│ Account │ Annual │ YTD     │ This Invoice │ After │ Var % │
│ 7100    │ 24,000 │ 21,500  │ 3,200        │24,700 │ 103%  │  (red row)
│ 7200    │ 18,000 │ 13,500  │   800        │14,300 │  79%  │  (green)
│ 7300    │ 12,000 │ 10,200  │   500        │10,700 │  89%  │  (yellow)
└───────────────────────────────────────────────────────────┘

[ ] I attest that this OVER_BUDGET expense is necessary and authorized
    (required to approve any red-flagged line)
```

The `budget_approval_attestation` checkbox must be checked before the Approve button enables when ≥1 OVER_BUDGET line is present.

Submit body extension:
```js
POST /api/jobs/{id}/hitl
{
  line_decisions: [...],
  budget_approval_attestation: true | false
}
```

The backend `submit_hitl_decisions` handler must accept and persist this attestation in `job.audit_log` (no schema change required — audit_log is `List[Dict]`).

**Dependencies:** Task 4 (job.budget_check populated)
**Validation:**
- Manual: open a job with OVER lines → see red rows, checkbox required
- Open a job with WARNING-only → see yellow rows, no attestation gate
- Submission without attestation when needed → button disabled

---

### Task 9 — Dashboard Budget Summary Card

**Files:** `frontend/coa.html` (or `frontend/index.html` if the dashboard lives there)

**Description:** Add a card on the church dashboard above the COA editor:

```
┌─ Budget Summary (FY 2026) ────────────────────────────┐
│ ▓▓▓▓▓░░░░░ 26%   $118,400 of $452,000 consumed        │
│ ✓ 58 within │ ⚠ 9 at risk │ ✗ 6 over budget          │
│                              [View variance report →] │
└───────────────────────────────────────────────────────┘
```

Source: `GET /budget/variance-report`. If no budget configured, render `[Upload Budget →]` linking to `/budget.html`.

**Dependencies:** Task 6
**Validation:** Manual visual check; numbers match `/budget.html`.

---

### Task 10 — Job Detail Budget Impact Strip

**Files:** `frontend/jobs.html`

**Description:** In the expanded job-detail panel (alongside Risk & Fraud), if `job.budget_check?.length`, render a compact strip per line:

```
Line: "Office supplies — Staples $324.50"
Account 7100 • Annual $24,000 • Before YTD $8,400 → After $8,724.50 (36%)  [green badge]
```

Use existing badge components; no new CSS.

**Dependencies:** Task 4
**Validation:** Manual: expand a job with budget data populated; values match `/budget.html`.

---

### Task 11 — Year-End Reset & Amendment Endpoints

**Files:** `backend/main.py`

**Description:** Implement `POST /budget/year-end-reset`:
- Requires `{ "confirm": true, "next_fiscal_year": int }`
- Sets `ctx.ytd_actuals = {}`
- If `roll_forward_plan = true`: keeps `ctx.budget` but updates `fiscal_year` and increments `amendment_number`. Otherwise sets `ctx.budget = None`.
- Appends to `ctx.warnings`: `"YTD reset on {iso} by {user}; previous total {x}"`

Amendment flow is just re-uploading via `/budget/import-spreadsheet`; the parser increments `amendment_number` on each upload after the first.

**Dependencies:** Task 6 (existing endpoints), Task 1 (amendment_number field)
**Validation:**
- POST without confirm → 400
- POST with confirm → ytd_actuals empty, audit recorded
- Amendment upload → amendment_number bumps, plan_date updates

---

### Task 12 — Test Suite

**Files:** `backend/tests/test_budget_*.py` (NEW directory if absent)

**Description:** Cover the deterministic logic exhaustively:

**12.1 — Schema round-trips** (`test_budget_schemas.py`):
- BudgetPlan / BudgetMonth / BudgetCheck JSON serialize/deserialize
- AccountingContext with budget loads & saves identically
- Backward compat: load `context_holy_comforter.json` (no budget) → no error

**12.2 — Parser** (`test_budget_parser.py`):
- Pure annual-only sheet
- Pure monthly-only sheet (ann derived)
- Mixed monthly + annual (consistent)
- Mixed monthly + annual (inconsistent → warning)
- Missing months filled with 0
- Unknown account number in budget → emitted in warnings, skipped
- CSV variant
- Multi-sheet xlsx (accounts + funds + budget) → all three parsed

**12.3 — Comparator** (`test_budget_comparator.py`):
- Within budget (10% consumed)
- Warning at 81% with default 80% threshold
- Warning at 81% with church threshold 0.85 → still WITHIN
- Over by exact penny
- Annual = 0, this_invoice > 0 → OVER
- Account not in budget → NO_BUDGET (skipped from escalations)
- Multi-line invoice with mixed statuses

**12.4 — Pipeline integration** (`test_budget_flow.py`):
- Invoice with all-within lines → status EMITTED, ytd updated
- Invoice with one OVER line → status PENDING_HITL even when reviewer found nothing
- HITL approve OVER → EMITTED, ytd reflects post-approval
- HITL reject OVER → ytd unchanged
- ctx.budget = None → flow unchanged from baseline (regression guard)

**12.5 — Endpoints** (`test_budget_api.py`):
- Upload → 200, get → matches
- Upload invalid file → 422
- Variance report aggregates correctly
- YTD reset requires confirm
- Threshold validation 0..1

**Dependencies:** Tasks 1–11
**Validation:** `pytest backend/tests/test_budget_*.py` all green; coverage ≥ 90% for `tools/budget_comparator.py`.

---

### Task 13 — Documentation & Template

**Files:**
- `frontend/templates/budget-template.xlsx` (NEW — generated programmatically and committed)
- `thoughts/shared/docs/BUDGET-FILE-FORMAT.md` (NEW)
- `thoughts/shared/docs/BUDGET-WORKFLOW.md` (NEW)

**Description:**

**Template xlsx:** A blank, well-labeled file with two sheets:
- "Accounts" — for COA upload (existing)
- "Budget" — columns `account_number, account_name, annual_budget, jan, feb, …, dec` with one row per active expense account (use Holy Comforter's COA as the seed). All amounts blank, ready for the church to fill in.

Generate with `openpyxl`; commit as binary; ship behind `[Download Template]` button (Task 7).

**Format guide:** Document column names, aliases, units (USD whole dollars or with decimals), what happens with missing months, what happens with unknown accounts.

**Workflow guide:** Annual cycle — upload at year start, review variance reports throughout year, year-end reset procedure, amendment process (re-upload increments amendment_number).

**Dependencies:** none after Task 1 lands
**Validation:** Open template in Excel; download from UI; round-trip parse → expected schema.

---

## Testing Strategy

| Layer | Tool | Goal |
|---|---|---|
| Schema | `pytest` + `pydantic` | Round-trip; backward-compat with old context JSONs |
| Parser | `pytest` + `openpyxl` | Real fixture xlsx → expected `BudgetPlan` |
| Comparator | `pytest` + parametrize | All branches of status enum; Decimal exactness |
| Pipeline | `pytest` async, mock pdf_extractor | End-to-end with synthetic invoice |
| API | `httpx` against `app` | Status codes, payload shapes |
| UI | manual on running dev server | Visual + interaction |

**Coverage gate:** `tools/budget_comparator.py` and budget paths in `flow.py` ≥ 90%.

**Property-based candidate (stretch):** `hypothesis` on `compare_to_budget` — generate random `(annual, ytd, this_invoice, threshold)` and assert the status-enum decision matches a reference truth-table. Worth doing because the function is small, pure, and total.

---

## Risks & Considerations

| Risk | Mitigation |
|---|---|
| **YTD drift** if the JSON file is corrupted or two pipelines write concurrently | Acceptable for v1 (single-process FastAPI). Document. Add file-locking (`fcntl.flock`) in `coa_store.save_accounting_context` if it bites. Long-term: move to SQLite. |
| **Stale YTD across restart** if a job EMITTED but `save_accounting_context` failed | Wrap the post-EMIT update in a try/except that logs but doesn't fail the request; on next startup, optionally reconcile by re-summing journal entries (deferred — JEs aren't persisted today). |
| **Budget plan mid-year amendments lose history** | `amendment_number` increments but old plans are overwritten. For v1 acceptable. If audit is needed, snapshot to `backend/data/budget_history_{cid}/{year}_v{n}.json` on each upload. |
| **Annual_total = 0 with positive invoice** | Comparator flags OVER_BUDGET (correct, prevents silent pass-through) |
| **Account in budget but inactive in COA** | Parser warning + skip; do not error |
| **Negative debits / credit-only postings** | Comparator skips (only debits count toward YTD) |
| **Threshold = 1.0** | All non-over lines are WITHIN; never WARNING — valid configuration |
| **Per-line budget escalation spam** | Reasons are appended to `reviewed.lines[].reasons[]` which already de-duplicates by string compare in the modal — no extra dedup needed unless user reports clutter |
| **Concurrency on `_jobs` dict + `ytd_actuals`** | Same risk as today's pipeline. No worse. |
| **Frontend cache when uploading new budget** | Add cache-busting query param on `loadBudget()` after upload (already a pattern in `coa.html`) |

---

## Estimated Complexity

| Task | Lines added | Effort |
|---|---|---|
| 1. Schemas | ~80 in schemas.py | S (1 hr) |
| 2. Parser extension | ~120 in spreadsheet_parser.py | M (3 hr) |
| 3. Comparator | ~150 new file | M (3 hr) |
| 4. Pipeline insert | ~40 in flow.py | S (1 hr) |
| 5. YTD update | ~25 in flow.py | S (1 hr) |
| 6. API endpoints | ~200 in main.py | M (3 hr) |
| 7. budget.html | ~400 lines new | L (5 hr) |
| 8. HITL modal extension | ~150 in jobs.html | M (3 hr) |
| 9. Dashboard card | ~60 in coa.html | S (1 hr) |
| 10. Job detail strip | ~80 in jobs.html | S (1 hr) |
| 11. Year-end endpoints | ~80 in main.py | S (1 hr) |
| 12. Test suite | ~600 across 5 files | L (6 hr) |
| 13. Docs + template | ~150 lines docs + xlsx | M (2 hr) |
| **Total** | ~2,135 LOC | **~31 hr** (≈ 4 working days) |

Critical path: 1 → 2 → 3 → 4 → 5 → 6 (everything else fans out from 6). Tasks 7, 8, 9, 10 can run in parallel once 6 is done. Tests (12) interleave with each backend task.

---

## Acceptance Criteria — Feature Complete

- [ ] Holy Comforter can upload `holy-comforter-fy26-budget.xlsx` via `/budget.html` and see all 73 expense accounts with monthly columns
- [ ] An invoice that pushes account 7100 over its $24,000 annual is routed to PENDING_HITL with the budget reason visible in the amber box
- [ ] Approving that invoice via HITL produces an EMITTED journal entry; `ytd_actuals["7100"]` increases by the invoice amount; the next refresh of `/budget.html` shows the updated bar
- [ ] Rejecting that invoice leaves YTD untouched
- [ ] Variance report at `/api/.../budget/variance-report` returns three buckets that sum to the configured account count
- [ ] Year-end reset zeros `ytd_actuals` and is captured in `ctx.warnings`
- [ ] All `pytest backend/tests/test_budget_*.py` pass; comparator coverage ≥ 90%
- [ ] Existing churches without a budget continue to operate unchanged (no `budget` field → Step 7b is skipped, no UI strip rendered)
