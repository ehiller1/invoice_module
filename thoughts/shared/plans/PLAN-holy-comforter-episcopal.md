# Implementation Plan: Holy Comforter Episcopal Church Profile in EIME

Generated: 2026-05-06
Author: plan-agent
Status: Ready for implementation

---

## Executive Summary

### What We're Building
A complete `AccountingContext` profile for **Holy Comforter Episcopal Church**
(`church_id = "holy_comforter"`, denomination `EPISCOPAL`) persisted as
`backend/data/context_holy_comforter.json`, indexed in ChromaDB for semantic
GL mapping, and discoverable via the existing `list_churches()` API.

### Why
EIME currently ships only with a UMC sample (`grace_umc`) and an empty
Presbyterian shell (`test_presbyterian.json`). To validate that the
denomination-aware pipeline (classifier → GL mapper → reviewer → journal
builder) handles **The Episcopal Church (TEC)** rules correctly, we need a
realistic Episcopal parish profile that exercises:

- **Diocesan Assessment** (apportionment-style obligation, distinct from UMC)
- **Church Pension Fund (CPF)** mandatory 18% clergy contribution
- **Rector's Discretionary Fund** (BOARD_DESIGNATED, IRS-substantiated)
- **Permanently restricted endowment** with separate principal/income accounts
- **Parochial Report** clergy compensation split across 4 distinct accounts

This profile becomes the canonical Episcopal demo and the test fixture for
Episcopal-specific denomination rules.

### Verified Codebase Facts (✓ VERIFIED by reading source)

| Fact | Evidence |
|------|----------|
| Persistence is flat JSON, no DB | `coa_store.save_accounting_context` writes via `Path.write_text(model_dump_json)` (coa_store.py:55-57) |
| File path pattern | `_ctx_path` returns `DATA_ROOT / f"context_{church_id}.json"` (coa_store.py:45-46) |
| **No `churches.json` index file exists** | `list_churches()` auto-discovers via `DATA_ROOT.glob("context_*.json")` (coa_store.py:68-82). The onboarding-context claim about `churches.json` is **incorrect** — drop that step. |
| ChromaDB index is rebuilt on save | `save_accounting_context` calls `_rebuild_index(ctx)` automatically (coa_store.py:57) |
| `EPISCOPAL` enum value exists | `DenominationType.EPISCOPAL = "EPISCOPAL"` (schemas.py:36) |
| Required AccountingContext fields | `church_id, church_name, denomination_type, fiscal_year, fiscal_year_start, accounts, funds` (schemas.py:195-208) |
| Apportionment model uses `pct_of_revenue` | `ApportionmentAccount` (schemas.py:190-192) — fits diocesan assessment cleanly |
| Allocation schedule basis is free-form string | `basis: str  # "square_footage" | "headcount" | "manual"` (schemas.py:185) — we can use `"pct_of_clergy_comp"` for CPF |

### Out of Scope
- New denomination rules in `denomination_rules.py` (separate plan; this only
  adds the **data** profile)
- Frontend church-selector UI changes (auto-picks up via `list_churches()`)
- Historical opening balances beyond illustrative `current_balance` per fund

---

## Codebase Reference Map

| Concern | File | Symbol |
|---------|------|--------|
| Schema definitions | `backend/models/schemas.py` | `AccountingContext`, `Account`, `Fund`, `AllocationSchedule`, `ApportionmentAccount`, `RestrictionClass`, `FundCategory`, `DenominationType` |
| Persistence + indexing | `backend/tools/coa_store.py` | `save_accounting_context`, `_rebuild_index`, `seed_sample_church` (template) |
| Existing UMC reference | `backend/data/context_grace_umc.json` | Use as structural template |
| Sample seed code (template to copy) | `backend/tools/coa_store.py:152-302` | `seed_sample_church()` |
| Denomination dispatch | `backend/tools/denomination_rules.py` | Future Episcopal rules go here (out of scope) |

---

## Implementation Tasks

There are **10 tasks**, ordered by dependency. Each is independently
verifiable. Tasks 1–8 produce the data; tasks 9–10 validate.

---

### Task 1 — Define Holy Comforter Funds (6 funds)

**Description:** Construct the `List[Fund]` covering the four restriction
classes Episcopal parishes typically maintain.

**Inputs:** None (pure data definition).

**Output:** Python list of `Fund` instances inside the new builder function.

**Funds to create:**

| fund_id | fund_name | restriction_class | fund_category | Episcopal note |
|---------|-----------|-------------------|---------------|----------------|
| `GEN` | General Operating | WITHOUT_RESTRICTION | GENERAL_OPERATING | Plate, pledge, unrestricted gifts; pays clergy comp, CPF, diocesan assessment |
| `OUTREACH` | Outreach & Mission | WITH_RESTRICTION_PURPOSE | TEMP_RESTRICTED_PURPOSE | Designated outreach gifts; pass-through to ERD, partner agencies |
| `MEMORIAL` | Memorial Gifts | WITH_RESTRICTION_PURPOSE | TEMP_RESTRICTED_PURPOSE | Donor-purposed gifts (altar flowers, music, sanctuary improvements) |
| `RECTOR_DISC` | Rector's Discretionary Fund | WITH_RESTRICTION_PURPOSE | **BOARD_DESIGNATED** | TEC Canon I.7; rector sole signatory for charitable aid; IRS-substantiated; never personal use |
| `ENDOW_PRIN` | Endowment — Principal | WITH_RESTRICTION_PERMANENT | PERMANENTLY_RESTRICTED | Corpus never spent (UPMIFA); maps to account 1900 |
| `ENDOW_INC` | Endowment — Income | WITH_RESTRICTION_PURPOSE | TEMP_RESTRICTED_PURPOSE | Spendable income from endowment (typ. 4–5% draw); maps to account 1910 |

**Validation:**
- [ ] Pydantic validates each Fund (run `Fund(**dict)` succeeds for all 6)
- [ ] All 6 `fund_id` values are unique
- [ ] At least one fund per restriction class is present
- [ ] `RECTOR_DISC` carries category `BOARD_DESIGNATED` (not generic restricted)

**Dependencies:** None.

---

### Task 2 — Define Asset, Liability, Net-Asset Accounts

**Description:** Build the 1000–3999 ranges. Episcopal parishes follow the
same NACUBO/balance-sheet structure as other 501(c)(3)s but typically split
endowment into **principal** (1900) and **accumulated income** (1910).

**Accounts:**

```
Assets (1000s)
  1010  Operating Cash                  Asset       GEN          WITHOUT
  1020  Outreach Cash                   Asset       OUTREACH     PURPOSE
  1030  Memorial Cash                   Asset       MEMORIAL     PURPOSE
  1040  Rector's Discretionary Cash     Asset       RECTOR_DISC  PURPOSE
  1100  Pledges Receivable              Asset       GEN          WITHOUT
  1500  Land                            Asset       GEN          WITHOUT
  1510  Church Buildings                Asset       GEN          WITHOUT
  1520  Parish Hall                     Asset       GEN          WITHOUT
  1530  Rectory                         Asset       GEN          WITHOUT
  1540  Organ & Liturgical Equipment    Asset       GEN          WITHOUT
  1900  Endowment Investments — Principal   Asset   ENDOW_PRIN   PERMANENT
  1910  Endowment Investments — Accumulated Income  Asset  ENDOW_INC  PURPOSE

Liabilities (2000s)
  2010  Accounts Payable                Liability   GEN          WITHOUT
  2020  Pass-Through Outreach Liability Liability   OUTREACH     PURPOSE
  2030  Payroll Liabilities             Liability   GEN          WITHOUT
  2040  CPF Payable                     Liability   GEN          WITHOUT
  2050  Diocesan Assessment Payable     Liability   GEN          WITHOUT

Net Assets (3000s)
  3100  Net Assets — Without Restriction      Equity  GEN          WITHOUT
  3200  Net Assets — Purpose Restricted       Equity  OUTREACH     PURPOSE
  3300  Net Assets — Endowment Principal      Equity  ENDOW_PRIN   PERMANENT
  3310  Net Assets — Endowment Income         Equity  ENDOW_INC    PURPOSE
```

**Episcopal-specific notes:**
- **1900/1910 split** is a TEC convention so the auditor can confirm corpus
  preservation under UPMIFA; principal account never receives expense debits.
- **2040 CPF Payable** holds 18% accrual until monthly remittance to CPF.
- **2050 Diocesan Assessment Payable** holds quarterly accrual until
  remittance to the diocese.

**Validation:**
- [ ] All `fund_id` references resolve to a Fund created in Task 1
- [ ] `restriction_class` matches the parent fund's class (no Asset on
      `RECTOR_DISC` with WITHOUT_RESTRICTION, etc.)
- [ ] Account numbers are unique

**Dependencies:** Task 1.

---

### Task 3 — Define Revenue Accounts (4000s)

**Description:** Episcopal-specific revenue lines.

```
4100  Pledge Income                       Revenue  GEN          WITHOUT
4110  Plate Offerings                     Revenue  GEN          WITHOUT
4120  Loose Plate / Visitor Offerings     Revenue  GEN          WITHOUT
4200  Designated Gifts — Outreach         Revenue  OUTREACH     PURPOSE
4210  Designated Gifts — Memorial         Revenue  MEMORIAL     PURPOSE
4300  Endowment Income Distributions      Revenue  ENDOW_INC    PURPOSE
4400  Investment Income                   Revenue  GEN          WITHOUT
4500  Facility Use / Wedding Fees         Revenue  GEN          WITHOUT
4900  Rector's Discretionary Contributions  Revenue  RECTOR_DISC PURPOSE
```

**Episcopal-specific notes:**
- **4900** must be a separate revenue account so the Vestry treasurer can
  verify discretionary-fund inflows match parishioner intent (TEC audit
  requirement).
- **4300** is the spendable draw from the endowment, not investment return on
  the principal — keeps parochial-report Schedule of Fund Balances clean.

**Validation:**
- [ ] 4900 fund_id is `RECTOR_DISC`, not `GEN`
- [ ] 4300 fund_id is `ENDOW_INC`, not `ENDOW_PRIN`

**Dependencies:** Tasks 1, 2.

---

### Task 4 — Define Personnel Expenses with Parochial-Report Split (5000s)

**Description:** Episcopal **Parochial Report** Schedule A requires clergy
compensation reported across at least these distinct lines. The COA must
mirror that split so reporting is a sum, not an estimate.

```
5100  Clergy Salary (Rector)              Expense  GEN  WITHOUT
5101  Clergy Housing Allowance            Expense  GEN  WITHOUT
5102  Clergy SECA Reimbursement           Expense  GEN  WITHOUT
5103  Clergy Continuing Education         Expense  GEN  WITHOUT
5104  Clergy Travel & Auto                Expense  GEN  WITHOUT
5210  CPF Pension Assessment (18%)        Expense  GEN  WITHOUT
5220  Clergy Healthcare Premium           Expense  GEN  WITHOUT
5221  Clergy Dental & Vision              Expense  GEN  WITHOUT
5222  Clergy Life & Disability            Expense  GEN  WITHOUT
5300  Lay Staff Wages — Parish Administrator  Expense  GEN  WITHOUT
5310  Lay Staff Wages — Music Director    Expense  GEN  WITHOUT
5320  Lay Staff Wages — Sexton            Expense  GEN  WITHOUT
5400  Lay Staff Benefits — Health         Expense  GEN  WITHOUT
5410  Lay Staff Benefits — Retirement (DTL)  Expense  GEN  WITHOUT
5420  Payroll Taxes (Employer FICA)       Expense  GEN  WITHOUT
```

**Episcopal-specific notes:**
- **5210 CPF** uses code `5210` (matches diocesan COA conventions). CPF
  assessment base = salary + housing + utilities + SECA + one-time bonuses.
- **5410 DTL** = Defined Contribution / Lay Pension via CPF Lay DC plan.
- **5102 SECA**: clergy are statutorily self-employed for SECA; reimbursement
  is an additional taxable line.

**Validation:**
- [ ] Account 5210 exists (required for CPF allocation schedule in Task 6)
- [ ] Accounts 5100, 5101, 5210, 5220 all exist (required for parochial split)

**Dependencies:** Tasks 1, 2.

---

### Task 5 — Define Ministry, Facility, Admin Expenses (6000–8000s)

**Description:** Standard parish expenses with Episcopal-specific labels.

```
Ministry (6000s)
  6100  Worship — Music & Choir          Expense  GEN          WITHOUT
  6110  Altar Guild & Communion Supplies  Expense  GEN         WITHOUT
  6120  Liturgical Vestments & Linens    Expense  GEN          WITHOUT
  6200  Christian Formation — Children   Expense  GEN          WITHOUT
  6210  Christian Formation — Youth (EYC)  Expense GEN         WITHOUT
  6220  Christian Formation — Adult      Expense  GEN          WITHOUT
  6300  Pastoral Care & Visitation       Expense  GEN          WITHOUT
  6400  Outreach — Pass-Through Disbursements  Expense  OUTREACH  PURPOSE
  6410  Episcopal Relief & Development (ERD)  Expense  OUTREACH  PURPOSE
  6500  Memorial Designated Disbursements  Expense  MEMORIAL    PURPOSE
  6900  Rector's Discretionary Disbursements  Expense  RECTOR_DISC  PURPOSE

Facility (7000s)
  7100  Mortgage / Rent                  Expense  GEN          WITHOUT
  7200  Utilities — Electric             Expense  GEN          WITHOUT
  7210  Utilities — Gas                  Expense  GEN          WITHOUT
  7220  Utilities — Water/Sewer          Expense  GEN          WITHOUT
  7230  Utilities — Internet/Phone       Expense  GEN          WITHOUT
  7300  Maintenance & Repairs            Expense  GEN          WITHOUT
  7310  Janitorial / Sexton Supplies     Expense  GEN          WITHOUT
  7320  Grounds & Landscaping            Expense  GEN          WITHOUT
  7400  Insurance — Property & Liability Expense  GEN          WITHOUT
  7410  Insurance — Workers Comp         Expense  GEN          WITHOUT
  7500  Technology & Software            Expense  GEN          WITHOUT

Administration (8000s)
  8100  Office Supplies                  Expense  GEN          WITHOUT
  8200  Legal & Audit                    Expense  GEN          WITHOUT
  8300  Bank Fees & Merchant Processing  Expense  GEN          WITHOUT
  8400  Stewardship Campaign             Expense  GEN          WITHOUT
  8410  Diocesan Assessment              Expense  GEN          WITHOUT
  8420  National Church / Province Pledge  Expense  GEN        WITHOUT
```

**Episcopal-specific notes:**
- **6900** is the *expense* counterpart of revenue 4900; both live in the
  `RECTOR_DISC` fund so the fund nets to zero when fully expended.
- **8410 Diocesan Assessment** is the canonical apportionment-equivalent
  account; the diocese typically charges ~10–15% of normal operating income
  (see Task 7).
- **8420** covers any voluntary remittance above mandatory assessment
  (rare but distinct line for transparency).
- **6410 ERD** broken out separately because Episcopal Relief & Development
  is a national-church-affiliated 501(c)(3) — useful for donor reporting.

**Validation:**
- [ ] Account 8410 exists (required for diocesan assessment apportionment)
- [ ] Accounts 6900 and 4900 share fund_id `RECTOR_DISC`

**Dependencies:** Tasks 1, 2.

---

### Task 6 — Define CPF Allocation Schedule (18% of clergy comp)

**Description:** The **Church Pension Fund** assessment is 18% of "Total
Assessable Compensation" (salary + housing + utilities + SECA reimbursement
+ one-time payments). Encode as an `AllocationSchedule`.

**Schedule:**

```python
AllocationSchedule(
    schedule_id="CPF_18PCT",
    name="Church Pension Fund — 18% Clergy Assessment",
    basis="pct_of_clergy_comp",
    allocations=[
        # Source accounts that compose the assessment base
        {"source_account": "5100", "include_pct": 100.0},  # Salary
        {"source_account": "5101", "include_pct": 100.0},  # Housing
        {"source_account": "5102", "include_pct": 100.0},  # SECA reimbursement
        # Target: post 18% of base to 5210, credit 2040
        {"target_expense_account": "5210",
         "target_liability_account": "2040",
         "rate_pct": 18.0},
    ],
    applies_to_categories=["CLERGY_COMPENSATION", "CLERGY_HOUSING",
                           "SECA_REIMBURSEMENT"],
)
```

**Episcopal-specific notes:**
- 18% rate is set by the General Convention; do **not** parameterize this as
  a configurable per-parish rate.
- The schedule is **informational** for now (the runtime allocator may not
  yet consume `pct_of_clergy_comp` basis); document this in the schedule's
  free-form fields. A follow-up task can wire it into `gl_mapper.py`.
- Validation that the schedule shape matches what `gl_mapper` consumes is
  Task 9, not here.

**Validation:**
- [ ] `Pydantic.AllocationSchedule(...)` validates without error
- [ ] All `source_account` and `target_*_account` numbers reference accounts
      created in Tasks 4 / 2

**Dependencies:** Tasks 2, 4.

---

### Task 7 — Define Diocesan Assessment Apportionment

**Description:** Use the existing `ApportionmentAccount` model
(schemas.py:190) which already maps cleanly: a fixed percentage of revenue
posted to a designated expense account.

**Apportionments:**

```python
apportionment_accounts = [
    ApportionmentAccount(account_number="8410", pct_of_revenue=Decimal("12.5")),
    # Optional: voluntary additional national-church support
    # ApportionmentAccount(account_number="8420", pct_of_revenue=Decimal("1.0")),
]
```

**Episcopal-specific notes:**
- **12.5%** is illustrative for planning. Most TEC dioceses charge between
  10% and 15% of "Normal Operating Income" (NOI = total operating revenue
  minus pass-through and capital). Document the placeholder in a
  `warnings` entry on the AccountingContext so the user knows to override.
- The pct is calculated against revenue accounts in the `GEN` fund only —
  pass-through and restricted gifts are excluded by diocesan canon.
  (Enforcement of "GEN-only" is a future `gl_mapper` enhancement; out of
  scope here.)

**Validation:**
- [ ] Account 8410 exists in the COA
- [ ] `pct_of_revenue` is a `Decimal`, not float (required by schema)

**Dependencies:** Task 5.

---

### Task 8 — Assemble & Persist AccountingContext

**Description:** Add a builder function `seed_holy_comforter()` to
`backend/tools/coa_store.py` (mirroring `seed_sample_church()` at lines
152–302) and call `save_accounting_context(seed_holy_comforter())` once.

**Code shape:**

```python
def seed_holy_comforter() -> AccountingContext:
    """Build the Holy Comforter Episcopal Church profile."""
    funds = [...]   # Task 1
    accounts = [...]  # Tasks 2, 3, 4, 5
    schedules = [...]  # Task 6
    apportionments = [...]  # Task 7
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
            "Diocesan assessment rate (12.5%) is a planning placeholder — "
            "confirm with diocese for actual rate and base definition.",
            "CPF allocation schedule is informational; gl_mapper integration "
            "pending.",
        ],
    )
```

**Then extend `ensure_seed()`** (coa_store.py:305-308):

```python
def ensure_seed() -> None:
    if not _ctx_path("grace_umc").exists():
        save_accounting_context(seed_sample_church())
    if not _ctx_path("holy_comforter").exists():
        save_accounting_context(seed_holy_comforter())
```

**Output artifact:**
- New function `seed_holy_comforter` in `backend/tools/coa_store.py`
- New file `backend/data/context_holy_comforter.json` (auto-created on first
  call to `save_accounting_context`)
- New ChromaDB collection `coa_holy_comforter` (auto-rebuilt by
  `_rebuild_index`)

**Validation:**
- [ ] `save_accounting_context(seed_holy_comforter())` returns without error
- [ ] `backend/data/context_holy_comforter.json` exists and is valid JSON
- [ ] `load_accounting_context("holy_comforter")` returns a populated
      `AccountingContext`
- [ ] `list_churches()` returns an entry with `church_id="holy_comforter"`,
      `denomination_type="EPISCOPAL"`

**Dependencies:** Tasks 1–7.

**Important:** Per onboarding context the user expected a `churches.json`
index update step. **This step is not needed** — `list_churches()` discovers
churches via `glob("context_*.json")` (verified at coa_store.py:68-82). The
plan omits it intentionally.

---

### Task 9 — Episcopal-Rule Coverage Validation

**Description:** Run a structured checklist against the persisted profile to
confirm every Episcopal accounting requirement called out in the brief is
representable.

**Checklist (each item must map to a specific account/fund/schedule):**

| Requirement | Required artifact | Verified? |
|-------------|-------------------|-----------|
| Diocesan Assessment | Account 8410 + ApportionmentAccount(8410) | [ ] |
| National Church Pledge | Account 8420 (optional, but present) | [ ] |
| CPF mandatory 18% | Account 5210 + AllocationSchedule `CPF_18PCT` + Liability 2040 | [ ] |
| Rector's Discretionary | Fund `RECTOR_DISC` (BOARD_DESIGNATED) + Revenue 4900 + Expense 6900 + Asset 1040 | [ ] |
| Endowment principal/income split | Fund `ENDOW_PRIN` (PERMANENT) + `ENDOW_INC` (PURPOSE) + Accounts 1900, 1910, 3300, 3310 | [ ] |
| Parochial Report clergy split | Accounts 5100, 5101, 5210, 5220 all present | [ ] |
| All four restriction classes represented | At least one fund per: WITHOUT, PURPOSE, PERMANENT (BOARD_DESIGNATED via category) | [ ] |

**Implementation:** A simple verification script in
`backend/data/_verify_holy_comforter.py` (or inline in a pytest if test
infra exists) that loads the context and asserts each row.

**Pseudocode:**

```python
ctx = load_accounting_context("holy_comforter")
assert ctx is not None
nums = {a.account_number for a in ctx.accounts}
assert {"8410", "5210", "4900", "6900", "1900", "1910",
        "5100", "5101", "5220", "1040", "2040"} <= nums
fund_ids = {f.fund_id for f in ctx.funds}
assert {"RECTOR_DISC", "ENDOW_PRIN", "ENDOW_INC"} <= fund_ids
rd = next(f for f in ctx.funds if f.fund_id == "RECTOR_DISC")
assert rd.fund_category == FundCategory.BOARD_DESIGNATED
ep = next(f for f in ctx.funds if f.fund_id == "ENDOW_PRIN")
assert ep.restriction_class == RestrictionClass.WITH_RESTRICTION_PERMANENT
assert any(s.schedule_id == "CPF_18PCT" for s in ctx.allocation_schedules)
assert any(a.account_number == "8410" for a in ctx.apportionment_accounts)
```

**Validation:**
- [ ] All 7 checklist rows pass
- [ ] No exceptions on `load_accounting_context`

**Dependencies:** Task 8.

---

### Task 10 — End-to-End Smoke Test (UI / API)

**Description:** Confirm the new profile is reachable from the running app.

**Steps:**

1. Start the backend (`./start.sh` from project root, or `uv run uvicorn
   backend.main:app --reload`).
2. Hit `GET /churches` (or whatever endpoint wraps `list_churches()` — locate
   in `backend/main.py`). Expect Holy Comforter in the response.
3. Hit `GET /coa/holy_comforter/search?q=clergy+pension` (or call
   `semantic_search("holy_comforter", "clergy pension", k=3)` directly in a
   Python REPL). Expect account **5210 CPF Pension Assessment** in the top
   results.
4. Switch the church selector in the frontend to Holy Comforter; upload a
   sample test invoice (e.g., one of the existing `audit_pdfs/`) and
   confirm the classifier/GL-mapper flow runs without unrecognized-account
   errors.
5. Inspect a generated journal entry — confirm fund_id values resolve and no
   "fund not found" warnings surface.

**Validation:**
- [ ] `list_churches()` includes Holy Comforter
- [ ] Semantic search returns Episcopal-specific accounts for relevant
      queries (CPF, diocesan, rector)
- [ ] At least one full invoice can be processed end-to-end against the
      Holy Comforter profile without crash
- [ ] No `warnings` of type "account not found" or "fund not found" in the
      pipeline output

**Dependencies:** Tasks 8, 9.

---

## Testing Strategy

**Layered approach, fastest to slowest:**

1. **Pydantic validation** (free): Constructing `AccountingContext(...)`
   inside `seed_holy_comforter()` runs full schema validation. If any
   account references a missing fund_id or any enum is wrong, this throws
   immediately.

2. **Structural assertions** (Task 9): Deterministic checks that every
   Episcopal artifact exists at its expected account number / fund id.
   Fast, no external dependencies.

3. **Semantic-index sanity** (Task 10 step 3): Confirms ChromaDB rebuild
   succeeded and BGE embeddings produce sensible matches for Episcopal
   terminology.

4. **End-to-end pipeline** (Task 10 steps 4–5): Validates the profile
   integrates with the live classifier → mapper → reviewer chain.

**No new pytest infrastructure required** — Tasks 9 and 10 can run as a
script in `backend/data/_verify_holy_comforter.py` and as manual UI/API
checks respectively.

---

## Risks & Considerations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `AllocationSchedule.basis="pct_of_clergy_comp"` not understood by `gl_mapper.py` yet | High | Document as informational in Task 6; add a `warnings` entry on the AccountingContext (Task 8); follow-up plan to wire `gl_mapper` |
| Diocesan assessment 12.5% is not the actual rate Holy Comforter pays | High | Surface as a `warnings` entry; user must override with real rate before production use |
| ChromaDB collection rebuild fails silently if ChromaDB dir is corrupt | Low | Existing code wraps `delete_collection` in try/except (coa_store.py:90-93); failure surfaces on next `semantic_search` call |
| Onboarding-context claim about `churches.json` being a real index file | Verified false | Drop that step (documented under Task 8); auto-discovery via `glob` is the actual mechanism |
| Restriction-class mismatch between Account and parent Fund | Medium | Task 9 checklist + Pydantic catches at save time |
| `BOARD_DESIGNATED` category combined with `WITH_RESTRICTION_PURPOSE` class | Intentional | Rector's Discretionary is technically board-designated *use* of donor-restricted funds; Episcopal canon treats it as restricted-by-purpose at the restriction level. This is correct — schema allows the combination. |

---

## Estimated Complexity

- **Lines of code:** ~250 (one builder function + ~50 accounts + 6 funds +
  1 schedule + 1–2 apportionments)
- **Files touched:** 1 (`backend/tools/coa_store.py`); 1 created
  (`backend/data/context_holy_comforter.json`, auto-generated)
- **External dependencies:** None (uses existing schema, persistence, indexer)
- **Implementation time:** 2–3 hours including verification script

---

## Handoff Checklist for Implementer

- [ ] Read the schema definitions at `backend/models/schemas.py:163-208`
      before writing the builder
- [ ] Use `seed_sample_church()` in `coa_store.py:152-302` as a structural
      template (do not copy UMC-specific accounts)
- [ ] Call `save_accounting_context(seed_holy_comforter())` exactly once;
      idempotency is handled by `ensure_seed()`
- [ ] Run Task 9 verification script before declaring complete
- [ ] Confirm `list_churches()` shows Holy Comforter (Task 10 step 2)
- [ ] **Do not** create or modify `backend/data/churches.json` — that file
      does not exist in this codebase

---

## Open Questions for Future Plans (Out of Scope)

1. Episcopal entries in `denomination_rules.py` (CPF base calculation,
   diocesan-assessment exclusion of restricted revenue)
2. Wiring `AllocationSchedule.basis="pct_of_clergy_comp"` into `gl_mapper`
3. Parochial Report export (Schedule A/B/C generation)
4. UPMIFA-compliant endowment-draw automation (4–5% rolling average)
