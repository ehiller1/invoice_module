# Budget Comparison Research: EIME Integration Patterns
Generated: 2026-05-06

## Codebase Baseline (VERIFIED)

Before the recommendations, here is what the codebase currently has and lacks — confirmed by reading the source:

| Item | Status | Location |
|---|---|---|
| `AccountingContext` schema | VERIFIED | `backend/models/schemas.py:195` |
| No `budget` field on `AccountingContext` | VERIFIED | schemas.py — only `parsonage_allowance_*` for budget-like tracking |
| No `ytd_actuals` dict | VERIFIED | schemas.py — `parsonage_allowance_used_ytd` exists but only for housing |
| `fund.current_balance` always `Decimal("0")` | VERIFIED | `context_holy_comforter.json:686` shows it set but never updated |
| `reviewer.py` escalation pattern | VERIFIED | `backend/tools/reviewer.py:96–99` — append to `escalation_items[]` → triggers HITL |
| Pipeline step 7b insertion point | VERIFIED | `backend/flow.py:182–188` — HITL gate checks `escalation_items`; budget check inserts before this |
| `spreadsheet_parser.py` sheet detection | VERIFIED | `backend/tools/spreadsheet_parser.py:52–58` — detects by column name presence |
| `import_coa_spreadsheet` endpoint pattern | VERIFIED | `backend/main.py:293` — mirrors what budget import should do |
| No persistence layer | VERIFIED | `ARCHITECTURE.md:84` — `flow._jobs` is an in-memory dict only |

---

## Budget File Format

### How churches typically organize budgets

Churches almost universally produce annual budgets approved by the vestry/session/board before the fiscal year begins. The standard format mirrors their GL account structure:

- **Row per account** — each expense account gets an annual appropriation
- **Monthly columns** — 12 monthly columns (Jan–Dec or fiscal months 1–12)
- **Fund separation** — either separate sheets per fund, or a fund column
- **Summary rows** — subtotals by ministry area (Worship, Administration, Outreach, etc.)

The most common software churches use: QuickBooks, Aplos, Realm, ACS Technologies, Shelby. All can export to Excel. The column structure is consistent:

```
Account Number | Account Name | Annual Budget | Jan  | Feb  | Mar  | ... | Dec
6100           | Clergy Salary | 84,000       | 7000 | 7000 | 7000 | ... | 7000
6200           | Utilities     | 18,000       | 1800 | 1200 | 1100 | ... | 1500
6310           | Music Ministry | 9,600       | 800  | 800  | 800  | ... | 800
```

### Detection signal for budget sheets

The existing spreadsheet parser detects sheet type by column names. Budget sheets are unambiguous if they contain any of:
- `annual_budget`, `budget`, `budgeted`
- Column names `jan`, `feb`, `mar` (month abbreviations)
- Column name `fiscal_month_1` through `fiscal_month_12`

Detection logic to add to `_parse_excel()`:
```python
has_budget_cols = any(col in df.columns for col in [
    "annual_budget", "budget", "budgeted", "jan", "feb", "mar"
])
if has_budget_cols:
    result["budget"] = _extract_budget_from_df(df)
```

This won't collide with accounts/funds sheets: accounts use `account_number/code`, funds use `fund_id/fund` — neither would have `jan`/`feb` columns.

### Recommended canonical format (CSV example)

```csv
account_number,account_name,annual_budget,jan,feb,mar,apr,may,jun,jul,aug,sep,oct,nov,dec
6100,Clergy Salary,84000,7000,7000,7000,7000,7000,7000,7000,7000,7000,7000,7000,7000
6200,Utilities,18000,2000,1800,1500,1200,1000,900,900,1000,1200,1500,1800,2200
6310,Music Ministry,9600,800,800,800,800,800,800,800,800,800,800,800,800
```

If monthly columns are omitted, treat the budget as evenly distributed (annual_budget / 12 per month).

### Budget metadata

The `BudgetPlan` model should carry:
```python
class BudgetPlan(BaseModel):
    fiscal_year: int
    accounts: List[AccountBudget]
    uploaded_at: datetime
    uploaded_by: Optional[str] = None
    amendment_number: int = 0          # 0 = original; 1,2,... = amendments
    amendment_notes: Optional[str] = None
```

### Mid-year budget amendments

Churches handle amendments by the vestry/board formally voting a revised budget (common after a major unexpected expense or pledge shortfall). Practically:
- Keep the original budget record and replace with the amended version
- `amendment_number` tracks how many amendments have occurred
- `amendment_notes` captures the reason (e.g., "HVAC replacement approved July vestry meeting")
- For the UI: display "Budget (Amended)" when `amendment_number > 0`
- For YTD tracking: recalculate remaining_budget against the amended annual figure — no need to retroactively re-check past transactions

---

## Comparison Logic

### What to compare

**Recommended: per-account comparison, with fund-level summary as secondary.**

Per-account is most actionable: finance committees approve budgets by account. Telling a reviewer "account 6200 Utilities is 94% consumed" is more useful than "GEN fund is 72% consumed."

Fund-level adds value for restricted funds: if the Outreach Fund has a $15,000 total budget and all accounts within it are only 40% consumed but the fund itself is at 95%, there is a cross-account reallocation happening worth flagging.

### Comparison dimensions

| Dimension | When to check | Trigger |
|---|---|---|
| Account-level annual | Always when budget exists | OVER when `ytd_actual + this_invoice > annual_budget` |
| Account-level period | When monthly columns provided | WARNING when month's total would exceed monthly allocation |
| Fund-level annual | When fund has a budget total | OVER when all accounts in fund exceed fund total |
| Pass-through accounts | Never | If account has no budget entry, skip comparison entirely |

### Variance thresholds

Based on standard church finance committee practice:

| Status | Condition | Action |
|---|---|---|
| `WITHIN_BUDGET` | projected_ytd <= 80% of annual_budget | No action — informational only in audit log |
| `WARNING` | 80% < projected_ytd <= 100% | Add to audit_log; show in job detail panel but do NOT escalate |
| `OVER_BUDGET` | projected_ytd > 100% of annual_budget | Escalate to HITL — requires Finance Committee approval |

The 80% threshold is the industry norm for church finance. Some churches use 90%; make it configurable per-church with a default of 0.80:
```python
class AccountingContext(BaseModel):
    ...
    budget_warning_threshold: float = 0.80   # configurable, e.g. 0.90 for conservative churches
```

### Edge cases

**Accounts with no budget entry:** Pass-through accounts (missions wire transfers, agency accounts). Skip comparison. Do not generate a WARNING or OVER_BUDGET. Only apply budget checking to accounts explicitly listed in `BudgetPlan.accounts`.

**Negative budget entries:** Rare but possible in budget amendments. Treat as zero — never flag as over-budget when budget is 0 or negative; instead treat as "no budget set."

**Multi-line invoices hitting same account:** Sum all postings to the same account_number from this invoice before comparing. A single invoice might have two line items both posted to 6200 Utilities.

**Restricted fund accounts:** Budget checking applies equally. A restricted fund with a purpose budget still needs to stay within that budget.

**Accounts not yet in COA but in budget:** Skip. Budget check only applies to accounts that appear in both `ctx.accounts` and `ctx.budget.accounts`.

---

## YTD Strategy

### Recommended approach: running tally in AccountingContext JSON

Given the constraint of no persistence layer (jobs are in-memory only), the only way to maintain cross-invoice YTD without adding a database is to store it in the church context JSON file.

```python
# Add to AccountingContext
ytd_actuals: Dict[str, Decimal] = Field(default_factory=dict)
# Keys are account_number strings; values are YTD debit totals
```

This survives server restarts because it is written to disk via `coa_store.save_accounting_context()` after each approved transaction.

### Update trigger

YTD should be updated **real-time as transactions are approved** — not calculated on-demand. The update happens in `_build_and_emit()` after `status = EMITTED`:

```python
# After journal entry is built and status set to EMITTED
if ctx.budget is not None and job.journal_entry is not None:
    for jel in job.journal_entry.lines:
        if jel.debit > Decimal("0"):  # only expense postings
            acct = jel.account_number
            ctx.ytd_actuals[acct] = ctx.ytd_actuals.get(acct, Decimal("0")) + jel.debit
    coa_store.save_accounting_context(ctx)
```

Only debits (expenses) count toward budget consumption. Credits are revenue or refunds — do not subtract from YTD (that creates a separate reconciliation problem).

### Fiscal year reset

YTD must reset when a new fiscal year begins. Two options:

**Option A (automatic):** At pipeline startup, check if `ctx.fiscal_year < current_year` — if so, reset `ytd_actuals = {}` and update `fiscal_year`. Risk: someone processes a prior-year invoice after year-end.

**Option B (manual):** Admin endpoint `POST /api/churches/{church_id}/budget/reset-ytd` that clears `ytd_actuals` and rolls the fiscal year. Safer — requires explicit action.

Recommend Option B with a UI button on the budget management page.

### Multi-year keying (optional enhancement)

For robustness, key `ytd_actuals` by `"{fiscal_year}:{account_number}"` rather than bare account number. This allows the system to hold two years of data during the year-end overlap period. For MVP, bare account_number is fine.

### Handling HITL-rejected invoices

If a job goes to PENDING_HITL and the human rejects it (action = REJECT), the journal entry is not built, so YTD is not updated. This is correct — rejected invoices should not count against budget.

If a job is approved at HITL with OVERRIDE postings, the override postings (not the original draft) should be used for YTD updates. The journal builder already uses override postings when present.

---

## Approval Workflow

### Decision rules

**OVER_BUDGET → mandatory HITL escalation.** No exceptions. The line is added to `reviewed.escalation_items[]` and will surface in the HITL modal with budget context in its `reasons[]`. Finance Committee must explicitly approve.

**WARNING → informational only.** The transaction is not blocked. The budget status is recorded in `audit_log` and shown in the job detail panel. The finance administrator sees it but is not required to act.

**WITHIN_BUDGET → no action.** Only appears in the `audit_log` entry for transparency.

### Override mechanism

In the HITL modal, when a line is escalated for budget overage, the reviewer has three choices (same as today):
- **APPROVED** — allows the posting as-is; YTD is updated; audit log records who approved and when
- **OVERRIDE** — reviewer specifies different postings (e.g., moves expense to a different account with remaining budget); YTD updates use override postings
- **REJECT** — posting is rejected; YTD not updated; invoice returned to originator

The existing `HITLLineDecision.notes` field is where the reviewer explains why they approved an over-budget item ("Emergency boiler repair, no alternative account available"). This note becomes part of the audit trail.

### Batch approval

The current HITL gate submits all line decisions together in one `HITLDecisions` object. Budget escalations follow the same pattern. No special batch handling needed — the existing mechanism works.

### Can multiple transactions be approved if combined they are within budget?

This is a UI/UX question, not a data model question. The budget check is per-invoice, per-transaction. EIME does not coordinate across concurrent in-flight jobs. If two invoices are processed simultaneously and both would put account 6200 at 95% consumed, both will get WARNING (not OVER) — the second one to commit to disk first wins. This is acceptable for MVP. A true locking mechanism would require a database.

### Audit trail

Every budget decision must be recorded. Two mandatory log entries:

1. **At pipeline time** (in `job.audit_log`): `"Budget check: account 6200 Utilities at 94% (OVER_BUDGET) — escalated to HITL"`
2. **At HITL approval** (in `job.audit_log`): `"Budget overage approved by John Smith (reviewer_id) at 2026-03-15T14:32:00 — notes: Emergency repair"`

This mirrors the existing audit_log pattern. The `HITLLineDecision.reviewer_id` and `approval_timestamp` fields already capture who approved and when.

For compliance, the existing PDF audit trail generator (`tools/pdf_generator.py`) should be extended to include budget variance and the approval decision.

---

## Agent Design

### Recommended: single tool, no separate agent

The existing pipeline does not use CrewAI agents in production — `run_pipeline()` in `flow.py` calls tool functions directly. Budget comparison should follow the same pattern: a single new tool module.

```
backend/tools/budget_comparator.py
  compare_to_budget(draft: DraftAllocations, ctx: AccountingContext) → BudgetCheck
```

This is consistent with how `reviewer.py`, `risk_assessor.py`, and `fraud_detector.py` are structured — each is a standalone deterministic function, not an LLM agent.

**Why not an agent?** Budget comparison is deterministic arithmetic: `(ytd_actual + this_invoice) / annual_budget`. An LLM agent adds latency and cost without adding value for a calculation that has no ambiguity.

### If an agent IS desired for narrative recommendations

A budget analyst agent (in `crews.py`) would be useful only for narrative recommendations: "This account is 95% consumed with 6 months remaining in the fiscal year — recommend Finance Committee review the operating budget." This is valuable in a future dashboard report, but not needed in the per-invoice pipeline.

If built, it would use the existing `Agent` + SKILL.md pattern. The SKILL.md would define:
- When to recommend a budget amendment
- Language for communicating overage to non-accountants
- How to suggest alternative accounts

### Insertion point in pipeline

```
flow.py:run_pipeline()

  ... Step 7: review_allocations() → reviewed ...

  # NEW Step 7b: budget comparison
  if ctx.budget is not None:
      budget_result = compare_to_budget(job.draft_allocations, ctx)
      job.budget_check = budget_result.model_dump()
      job.audit_log.append({...})

      for line_check in budget_result.lines:
          if line_check.status == BudgetLineStatus.OVER_BUDGET:
              if line_check.line_id not in reviewed.escalation_items:
                  reviewed.escalation_items.append(line_check.line_id)
                  # inject reason into the matching ReviewedLine
                  for rl in reviewed.lines:
                      if rl.line_id == line_check.line_id:
                          rl.reasons.append(line_check.recommendation)
                          break

  # Step 8: HITL gate (existing — now includes budget escalations)
  if reviewed.escalation_items:
      _update_job(job, ProcessingStatus.PENDING_HITL)
      return
```

### Should budget check run before or after GAAP review?

After. Reasoning:
- GAAP review (Step 7) may already escalate a line for unrelated reasons. If a line is already escalated, the budget overage context is still injected into its reasons — additive, not duplicative.
- A line that fails GAAP (e.g., restricted fund mismatch) would be rejected before it ever posts, so its YTD impact is moot. Running budget after GAAP avoids adding budget noise to already-rejected lines.
- The draft postings produced by GL mapping (Step 6) are already normalized and fund-assigned before budget check needs them.

The budget check reads `job.draft_allocations` (already computed in Step 6). It does not need any output from the GAAP reviewer except the `reviewed` object to inject reasons into.

---

## UI Patterns

### HITL modal integration

The HITL modal (`openHITL()` in `jobs.html`) already renders `reviewed.lines[].reasons[]` as a list in an amber alert box. Budget reasons inject into `reasons[]` like any other escalation cause. The existing render code handles this with no changes needed:

```
[Amber box in modal]
• Missions pass-through requires committee attestation.
• Budget overage: account 6200 Utilities — $17,842 of $18,000 annual budget consumed
  (99.1%). This invoice adds $850, would exceed by $692.
```

The `recommendation` field on `BudgetLineCheck` should be written as a human-readable sentence in this format.

### Job detail panel — budget check section

The jobs.html detail panel has a pattern for Risk and Fraud sections (expandable divs with colored badges). Add a "Budget Check" section following the same pattern:

```
Budget Check                          [OVER BUDGET badge in red]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Account         Budget    YTD Before  This Invoice  After      Status
6200 Utilities  $18,000   $17,842     $850          $18,692    OVER (103.8%)
6310 Music      $9,600    $7,200      $800          $8,000     83.3% ⚠
6400 Admin      $12,000   $8,500      $1,200        $9,700     80.8% ✓
```

Color coding:
- Red row + "OVER" badge: `status == OVER_BUDGET`
- Amber row + warning icon: `status == WARNING` (>80%)
- Normal row: `WITHIN_BUDGET`

This section should only appear when `job.budget_check` is not null.

### Dashboard budget summary view (`/budget.html`)

New page with three sections:

1. **Budget upload** — drag-and-drop Excel/CSV import, mirrors the COA upload UI. Shows current budget fiscal year and amendment number after upload.

2. **YTD variance table** — per-account: Annual Budget | YTD Actual | Remaining | % Consumed | Status. Filterable by ministry area. Sortable by % consumed (descending) to surface highest-risk accounts.

3. **Fund-level summary** — per-fund: Total Budgeted | YTD Actual | Remaining | % Consumed. Shows restricted vs. unrestricted breakdown.

The variance table data comes from `GET /api/churches/{church_id}/budget/variance`.

### Budget override UX

When a user approves an over-budget line in the HITL modal, they should see a confirmation nudge:
```
[Checkbox] I confirm Finance Committee approval for this budget overage.
```

This maps to the existing `missions_attestation: bool` field on `HITLLineDecision` — or a new `budget_approval_attestation: bool` could be added. The simplest approach: reuse `missions_attestation` for budget overages too, and the reviewer notes field captures the specifics.

### Budget variance percentages

Always display as percentage of annual consumed, not remaining:
- "95% of annual budget used" is more intuitive than "5% remaining"
- Use color: green < 70%, yellow 70–90%, orange 90–100%, red > 100%
- Show the absolute dollar amounts alongside the percentage

---

## Implementation Recommendations

### Priority order

1. **Schemas first** (`schemas.py`) — add `BudgetPlan`, `AccountBudget`, `BudgetPeriod`, `BudgetLineCheck`, `BudgetCheck`, `BudgetLineStatus`, extend `AccountingContext`, extend `ProcessingJob`. This is the contract everything else depends on.

2. **Spreadsheet parser extension** (`spreadsheet_parser.py`) — add budget sheet detection and `_extract_budget_from_df()`. This is self-contained and testable independently.

3. **Budget comparator tool** (`tools/budget_comparator.py`) — pure function, no I/O, fully unit-testable with mock data. The core algorithm.

4. **Pipeline integration** (`flow.py`) — insert Step 7b and the YTD update after `_build_and_emit`. Two small insertions.

5. **API endpoints** (`main.py`) — add budget import, get, put, variance, and reset-ytd endpoints. Mirror the COA import endpoint pattern exactly.

6. **Frontend** — extend jobs.html with budget panel, extend HITL modal, add budget.html page.

### Test data recommendation

Extend `context_holy_comforter.json` with a `budget` section for testing. Use realistic Episcopal church budget proportions:
- Clergy and staff: ~50% of operating budget
- Building/utilities: ~20%
- Program/ministry: ~15%
- Administration: ~10%
- Mission/outreach: ~5%

A test scenario: invoice for $850 to Utilities (6200) where YTD is already $17,842 of $18,000 annual — triggers OVER_BUDGET, escalates to HITL.

### Key constraints from existing codebase

- All Pydantic models: inherit `BaseModel` from pydantic v2, use `Field(default_factory=...)` for mutable defaults, use `Decimal` for all monetary values (not `float`)
- New tool modules: plain Python functions, no class required, same pattern as `reviewer.py`
- Context mutations: always save via `coa_store.save_accounting_context(ctx)` — this also rebuilds ChromaDB index
- Frontend: Tailwind via CDN, vanilla JS with `async/await fetch()`, navy/gold color palette
- HITL reasons: must be plain English strings in `reviewed.lines[].reasons[]` — no HTML, no markdown

### What not to build for MVP

- Do not build a true database for journal entry persistence — the JSON-based YTD tally is sufficient
- Do not build cross-invoice locking — acceptable race condition for MVP
- Do not build a budget agent (CrewAI) — the deterministic tool is sufficient and faster
- Do not build fund-level budget comparison for MVP — account-level is what finance committees use
- Do not build automatic fiscal year rollover — manual reset via endpoint is safer

