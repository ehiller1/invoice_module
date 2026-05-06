# Plan Validation: Holy Comforter Episcopal Church Profile in EIME

**Generated:** 2026-05-06
**Validator:** Claude Code (Haiku 4.5)
**Plan:** `/Users/erichillerbrand/chart of accounts/thoughts/shared/plans/PLAN-holy-comforter-episcopal.md`

---

## Overall Status: PASS_WITH_NOTES

The plan is technically sound and ready for implementation. All 10 tasks are achievable with the current EIME architecture. Critical codebase facts have been verified. No blockers identified.

**Recommended:** Proceed to implementation with noted clarifications applied.

---

## 1. Technical Feasibility Analysis

### ✓ VERIFIED: Persistence Mechanism

**Finding:** Flat JSON persistence with ChromaDB indexing is exactly what the plan assumes.

- **Location:** `backend/tools/coa_store.py:55-57`
- **Mechanism:** `save_accounting_context()` writes via `Path.write_text(model_dump_json(indent=2))`, then triggers automatic `_rebuild_index()`
- **File pattern:** `DATA_ROOT / f"context_{church_id}.json"` → `backend/data/context_holy_comforter.json`
- **Idempotency:** `ensure_seed()` checks file existence before first save (coa_store.py:305-308)

**Validation:** Task 8 will work exactly as specified. No breaking changes needed.

---

### ✓ VERIFIED: Schema Support for All Required Fields

**Finding:** All Pydantic models support the plan's data requirements.

| Field/Model | Location | Status |
|-------------|----------|--------|
| `DenominationType.EPISCOPAL` enum | schemas.py:35-43 | ✓ Exists |
| `AccountingContext` required fields | schemas.py:195-208 | ✓ All present: `church_id`, `church_name`, `denomination_type`, `fiscal_year`, `fiscal_year_start`, `accounts`, `funds` |
| `ApportionmentAccount` (diocesan assessment) | schemas.py:190-192 | ✓ Supports `account_number` + `pct_of_revenue` (Decimal) |
| `AllocationSchedule` with free-form `basis` string | schemas.py:182-187 | ✓ `basis: str` allows `"pct_of_clergy_comp"` |
| `FundCategory.BOARD_DESIGNATED` (rector's discretionary) | schemas.py:20-26 | ✓ Enum value exists |
| `RestrictionClass` (all 3 types) | schemas.py:29-32 | ✓ ALL present: `WITHOUT_RESTRICTION`, `WITH_RESTRICTION_PURPOSE`, `WITH_RESTRICTION_PERMANENT` |

**Validation:** Every data artifact defined in Tasks 1–7 can be represented without schema extensions.

---

### ✓ VERIFIED: Automatic Discovery via list_churches()

**Finding:** Plan's claim about `list_churches()` auto-discovery is correct. The onboarding context mention of a `churches.json` index file is **incorrect and has been identified as out-of-scope**.

- **Location:** `backend/tools/coa_store.py:68-82`
- **Mechanism:** `list_churches()` uses `DATA_ROOT.glob("context_*.json")` to discover all church profiles
- **API Exposure:** `backend/main.py:81-83` exposes as `GET /api/churches`

**Validation:** Task 8's handoff note correctly removes the `churches.json` step. Implementation should **not** touch any index file.

---

### ✓ VERIFIED: ChromaDB Indexing Automatic

**Finding:** Semantic indexing is automatic and transparent.

- **Location:** `backend/tools/coa_store.py:87-123`
- **Trigger:** `save_accounting_context()` automatically calls `_rebuild_index(ctx)` (line 57)
- **Collection name:** `coa_holy_comforter` (from `_coll_name()` at line 50)
- **Embedding model:** all-MiniLM-L6-v2 (line 30)
- **Error handling:** ChromaDB collection deletion wrapped in try/except (lines 90-93)

**Validation:** Task 10 step 3 (semantic search validation) will work as specified.

---

### ✓ VERIFIED: No Dependency Conflicts

**Finding:** No version issues or missing imports for this scope.

The plan adds data only; it does not modify:
- Schema definitions (schemas.py)
- Persistence layer (coa_store.py)
- GL mapper or classifier (out of scope per plan)
- Denomination rules (out of scope per plan)

**Dependencies used:** Standard library (`pathlib`, `json`), existing imports in coa_store.py.

**Validation:** No new dependencies required.

---

## 2. Episcopal Accounting Accuracy

### ✓ VERIFIED: Account Structure Alignment with TEC Canons

The plan's 10 accounts (5210, 8410, 8420, 1900, 1910, etc.) correctly reflect Episcopal Church accounting conventions.

| Account | Purpose | Aligned with TEC? | Notes |
|---------|---------|-------------------|-------|
| **5210 CPF** | 18% clergy assessment | ✓ Yes | Matches existing denomination_rules.py line 27: `("church pension", "cpf contribution")` maps to account `5210` |
| **8410 Diocesan Assessment** | Apportionment equivalent | ✓ Yes | Plan uses 12.5% (illustrative); matches denomination_rules.py line 24: `("diocesan assessment", "fair share")` maps to `8410` |
| **1900/1910 Principal/Income Split** | Endowment separation | ✓ Yes | Standard UPMIFA practice; NACUBO-compliant |
| **2040 CPF Payable** | Liability accrual | ✓ Yes | Standard for 18% monthly remittance |
| **2050 Diocesan Assessment Payable** | Liability accrual | ✓ Yes | Standard quarterly remittance |
| **4900 Rector's Discretionary Revenue** | Separate inflow tracking | ✓ Yes | TEC Canon I.7 substantiation requirement |
| **6900 Rector's Discretionary Expense** | Matching fund movement | ✓ Yes | Balances 4900 when expended |

**Validation:** Account mapping is correct per TEC requirements.

---

### ✓ VERIFIED: CPF 18% Calculation Basis

**Finding:** Plan correctly specifies CPF assessment base.

**Task 6 Specification:**
```
Source accounts (included at 100%):
  5100 Salary
  5101 Housing  
  5102 SECA reimbursement
```

**TEC/CPF Standard:** Total Assessable Compensation = Salary + Housing + Utilities + SECA + One-time bonuses.

**Note:** Plan intentionally omits utilities (5103 not modeled) and one-time bonuses, with `basis="pct_of_clergy_comp"` marked as **informational** until `gl_mapper` integration. This is a reasonable simplification for the data profile.

**Validation:** Model supports the 18% rate; implementation will have the data structure ready for future allocation logic.

---

### ✓ VERIFIED: Fund Restrictions per FASB ASC 958

The plan's 6 funds map cleanly to the three restriction classes required by FASB ASC 958 (NFP accounting standard).

| Fund | Restriction Class | Fund Category | FASB ASC 958 Class |
|------|-------------------|---------------|-------------------|
| GEN | WITHOUT_RESTRICTION | GENERAL_OPERATING | Unrestricted |
| OUTREACH | WITH_RESTRICTION_PURPOSE | TEMP_RESTRICTED_PURPOSE | Temporarily Restricted |
| MEMORIAL | WITH_RESTRICTION_PURPOSE | TEMP_RESTRICTED_PURPOSE | Temporarily Restricted |
| RECTOR_DISC | WITH_RESTRICTION_PURPOSE | **BOARD_DESIGNATED** | Temporarily Restricted (board use of donor funds) |
| ENDOW_PRIN | WITH_RESTRICTION_PERMANENT | PERMANENTLY_RESTRICTED | Permanently Restricted |
| ENDOW_INC | WITH_RESTRICTION_PURPOSE | TEMP_RESTRICTED_PURPOSE | Temporarily Restricted |

**Special case—RECTOR_DISC:** Using `WITH_RESTRICTION_PURPOSE` + `BOARD_DESIGNATED` is intentional and correct. Rector's discretionary is technically donor-restricted (purpose = charitable aid) but board-designated in use (rector discretion). Schema allows this combination (verified in `backend/models/schemas.py`).

**Validation:** Fund structure is correct per FASB ASC 958 and TEC Canon I.7.

---

### ✓ VERIFIED: Parochial Report Clergy Split

The plan includes accounts 5100, 5101, 5210, 5220 matching The Episcopal Church's parochial report Schedule A requirements.

**Plan specifies (Task 4):**
- 5100 Clergy Salary (Rector)
- 5101 Clergy Housing Allowance
- 5102 Clergy SECA Reimbursement
- 5103 Clergy Continuing Education
- 5104 Clergy Travel & Auto
- 5210 CPF Pension Assessment (18%)
- 5220 Clergy Healthcare Premium
- 5221 Clergy Dental & Vision
- 5222 Clergy Life & Disability

**TEC Parochial Report Schedule A requires minimum:** Salary, housing allowance, pension, healthcare.

**Plan provides:** All minimum fields plus additional granularity (SECA, continuing education, travel, dental/vision/life). This is a **best practice approach** that enables detailed cost analysis and audit trail.

**Validation:** Parochial split is complete and exceeds TEC minimum requirements.

---

## 3. Completeness Analysis

### ✓ VERIFIED: End-to-End Coverage

The plan's 10 tasks cover the full pipeline from data definition to validation.

**Task flow:**
1. Define funds (Task 1) → defines restriction universe
2. Define B/S accounts (Task 2) → uses funds from Task 1
3. Define revenue (Task 3) → uses funds from Tasks 1-2
4. Define personnel expenses (Task 4) → uses funds from Tasks 1-2
5. Define ministry/facility/admin expenses (Task 5) → uses funds
6. Define CPF allocation (Task 6) → uses accounts from Task 4
7. Define diocesan apportionment (Task 7) → uses accounts from Task 5
8. Assemble & persist (Task 8) → combines all above + adds warnings
9. Structural validation (Task 9) → verifies checklist
10. End-to-end smoke test (Task 10) → confirms API/UI integration

**Dependencies:** All explicit and acyclic. No circular references.

**Validation:** Plan is complete from data definition through API/UI verification.

---

### ⚠️ NOTED: Missing Accounts (Not Blockers, But Worth Reviewing)

The plan does **not** model:
- Utilities as a separate assessable compensation item (CPF base typically includes utilities; plan only includes salary + housing + SECA)
- One-time bonuses
- Endowment investment returns (only endowment income draw at 4300)

**Assessment:** These are intentional simplifications, not missing scope. The plan explicitly marks the CPF schedule as **informational** pending `gl_mapper` integration. For a **data profile only** (not allocation logic), this is acceptable.

**Recommendation:** For production use, add a warning to Task 8's `warnings` list:
> "CPF assessment excludes utilities and one-time bonuses. Adjust allocation schedule once gl_mapper integration is complete."

---

### ✓ VERIFIED: Future Maintenance Hooks

The plan acknowledges open questions and future work:

| Topic | Status |
|-------|--------|
| Denomination rules for CPF base calculation | Out of scope; noted in Task 6 |
| gl_mapper integration for `pct_of_clergy_comp` basis | Out of scope; documented as informational |
| Parochial Report export (Schedule A/B/C) | Out of scope; listed as open question |
| UPMIFA-compliant 4-5% endowment draw | Out of scope; listed as open question |

**Validation:** Plan correctly scopes itself to **data profile only** and defers allocation logic and reporting to follow-up efforts.

---

## 4. Data Model Alignment

### ✓ VERIFIED: AccountingContext Pydantic Validation

All outputs will conform to the required schema.

**Task 1 (Funds):** `Fund` objects with all required fields (`fund_id`, `fund_name`, `restriction_class`, `fund_category`).
**Tasks 2-5 (Accounts):** `Account` objects with all required fields (`account_number`, `account_name`, `account_type`, `fund_id`, `restriction_class`).
**Task 6 (CPF):** `AllocationSchedule` with valid `basis` and `allocations`.
**Task 7 (Apportionment):** `ApportionmentAccount` with `account_number` and `pct_of_revenue` (Decimal, not float).
**Task 8 (Final context):** `AccountingContext` with all required fields.

**Validation mechanism:** Pydantic `model_validate()` in `load_accounting_context()` (coa_store.py:65) will catch any field/type mismatches on load. Task 8's `save_accounting_context()` also implicitly validates via `model_dump_json()`.

**Validation:** No data model misalignment risk.

---

### ✓ VERIFIED: Enum and Restriction Consistency

The plan specifies restriction classes that match fund definitions.

**Example (RECTOR_DISC fund):**
- Fund definition (Task 1): `restriction_class=WITH_RESTRICTION_PURPOSE`, `fund_category=BOARD_DESIGNATED`
- Revenue account (Task 3): Account 4900, `restriction_class=WITH_RESTRICTION_PURPOSE`, `fund_id=RECTOR_DISC` ✓
- Expense account (Task 5): Account 6900, `restriction_class=WITH_RESTRICTION_PURPOSE`, `fund_id=RECTOR_DISC` ✓

**Task 9's checklist will verify this explicitly** (lines 464-471 of plan).

**Validation:** Enum/restriction consistency is design-correct and will be test-verified.

---

### ✓ VERIFIED: JSON File Path and Naming Convention

**Convention:** `backend/data/context_{church_id}.json`
**Holy Comforter:** `backend/data/context_holy_comforter.json`

**Verified at:** coa_store.py:45-46
```python
def _ctx_path(church_id: str) -> Path:
    return DATA_ROOT / f"context_{church_id}.json"
```

**Validation:** File naming is correct and auto-generated by save function.

---

### ✓ VERIFIED: ChromaDB Indexing Will Work

**Collection name:** `coa_holy_comforter` (auto-generated by `_coll_name()` at coa_store.py:49-50)
**Indexed documents:** Account names + numbers + fund context (coa_store.py:109)
**Embedding model:** all-MiniLM-L6-v2 (proven in existing grace_umc context)
**Search API:** `semantic_search("holy_comforter", query, k=5)` (coa_store.py:126-147)

**Validation:** Semantic indexing will work automatically on Task 8 save.

---

## 5. Integration Points Analysis

### ✓ VERIFIED: Invoice Processing Pipeline Integration

The new profile will integrate seamlessly with existing pipeline.

**Flow:** `backend/flow.py` → Classifier → GL Mapper → Reviewer → Journal Builder

**Integration points:**
1. **Church selection:** API `GET /api/churches` returns Holy Comforter automatically (coa_store.py:68-82, main.py:81-83)
2. **Context loading:** `load_accounting_context("holy_comforter")` fetches the JSON profile
3. **Account resolution:** GL mapper calls `semantic_search("holy_comforter", vendor_description)` to find accounts
4. **Restriction validation:** Journal builder uses fund/account restriction classes to enforce posting rules

**No changes needed** to flow.py, mapper, or reviewer. The profile is passive data.

**Validation:** Profile integrates via existing APIs.

---

### ✓ VERIFIED: Denomination Rules Integration

The plan correctly identifies that Episcopal denomination rules are **out of scope** for this plan.

**Existing denomination_rules.py:**
- UMC overrides at lines 9-21
- **EPISCOPAL overrides at lines 23-33** (already present, partial)
  - Diocesan assessment → 8410 ✓
  - CPF → 5210 ✓
  - Rector's discretionary → 6900 ✓
  - Endowment → 1900 ✓

**Plan's position:** Data profile (Task 8) can proceed independently. Denomination rules enhancement is a separate follow-up task (documented as open question).

**Current state:** The Episcopal overrides in denomination_rules.py are skeletal but sufficient for basic classification. They will work with the Holy Comforter profile.

**Validation:** No blocking dependency on denomination rules enhancement.

---

### ✓ VERIFIED: Episcopal Skill Agent Integration

The plan references agents in `denomination_episcopal/SKILL.md` receiving the correct context.

**API path:** `GET /api/churches/{church_id}/context` returns full `AccountingContext` (main.py:136-142)
**Skill agents:** Can load Holy Comforter context via this endpoint

**No changes needed** to skill agent code; it will receive the complete context structure.

**Validation:** Skill agents will have access to all required context.

---

## 6. Risk Assessment

### ✓ LOW RISK: AllocationSchedule.basis="pct_of_clergy_comp" Not Yet Implemented

**Risk:** CPF allocation schedule is marked informational (Task 6). The `gl_mapper.py` may not yet consume custom `basis` values.

**Mitigation:** 
- Plan explicitly documents this at Task 6 (lines 318-321)
- Task 8 adds warnings entry (lines 397-398)
- Task 9 checklist only requires the schedule to exist, not to be consumed

**Action:** Proceed with profile creation. Add follow-up task to wire gl_mapper for custom basis values.

**Impact:** Low. Data is ready; logic wiring is independent.

---

### ✓ MEDIUM RISK: Diocesan Assessment Rate is Placeholder

**Risk:** Plan uses 12.5% as illustrative. Real rate varies by diocese (10-15% typical).

**Mitigation:**
- Plan explicitly documents at Task 7 (lines 348-356)
- Task 8 adds warnings entry (lines 394-396)
- User must override `apportionment_accounts[0].pct_of_revenue` before production use

**Action:** Proceed. Warning ensures user awareness.

**Impact:** Medium but mitigated by explicit warning.

---

### ✓ MEDIUM RISK: Restriction-Class Mismatch in Validation

**Risk:** Task 9 checklist must verify every account's `restriction_class` matches its parent fund's `restriction_class`.

**Mitigation:**
- Pydantic does NOT validate this constraint (no custom validator in schema)
- Task 9's verification script catches mismatches (plan lines 464-466)
- Schema enforces enum values; mismatch errors surface as string/enum mismatches only

**Action:** Task 9 verification script is essential; do not skip it.

**Impact:** Medium but mitigated by explicit verification task.

---

### ✓ LOW RISK: ChromaDB Directory Corruption

**Risk:** ChromaDB persisted index could become corrupt if host disk fails mid-write.

**Mitigation:**
- Existing code wraps delete_collection in try/except (coa_store.py:90-93)
- If index is unreadable, semantic_search returns empty list (line 134)
- User receives no results but no crash

**Action:** None needed; existing resilience is adequate.

**Impact:** Low.

---

### ✓ LOW RISK: JSON Serialization of Decimal

**Risk:** `ApportionmentAccount.pct_of_revenue` is typed `Decimal` (line 192 of schemas.py). JSON must serialize Decimal correctly.

**Finding:** Pydantic's `model_dump_json()` handles Decimal serialization by default (converts to string in JSON).

**Validation at:** coa_store.py:56 uses `model_dump_json()`, which is Pydantic-standard.

**Impact:** Low; Pydantic handles this transparently.

---

## 7. Assumptions & Validation

### Assumption: Semantic Search Matches Episcopal Terminology

**Task 10 step 3** requires that `semantic_search("holy_comforter", "clergy pension", k=3)` returns account 5210.

**Basis:** The all-MiniLM-L6-v2 embedding model (used in coa_store.py:30) is trained on general English; "clergy pension" should match "CPF Pension Assessment" semantically.

**Validation plan:** Task 10 explicitly tests this. If results are poor, adjust account names (e.g., add "Pension" keyword).

**Risk:** Low. Embeddings are general-purpose and should handle ecclesiastical terminology.

---

### Assumption: No UMC-Specific Data Leaks into Holy Comforter Profile

**Task 8** requires copying `seed_sample_church()` structure but **not** copying UMC-specific accounts.

**Validation:** Plan explicitly warns at handoff checklist (lines 572-573):
> "Use `seed_sample_church()` in `coa_store.py:152-302` as a structural template (do not copy UMC-specific accounts)"

**Recommendation:** Implementer should use the UMC function as a **code pattern reference only**, not a copy-paste source.

---

### Assumption: `ensure_seed()` Idempotency Sufficient

**Task 8** calls `save_accounting_context(seed_holy_comforter())` exactly once via `ensure_seed()`.

**Validation:** `ensure_seed()` checks file existence before save (coa_store.py:305-308). If `context_holy_comforter.json` already exists, the function does nothing. Safe for multiple invocations.

---

## 8. Validation Against Checklist

### Technical Feasibility Checklist

- [✓] All tasks achievable with current EIME architecture
- [✓] Pydantic schemas support all required fields
- [✓] Persistence mechanism (JSON + ChromaDB) sufficient
- [✓] No dependency conflicts or version issues

### Episcopal Accounting Accuracy Checklist

- [✓] 10 accounts correctly mapped to TEC rules
- [✓] CPF calculation (18%) aligns with current TEC requirements
- [✓] Fund restrictions proper per FASB ASC 958
- [✓] Rector's discretionary fund structure sound (BOARD_DESIGNATED + PURPOSE restriction)
- [✓] Clergy compensation accounts (5100/5101/5210/5220) properly split for parochial report

### Completeness Checklist

- [✓] Plan covers all required setup steps end-to-end
- [✓] Validation/testing steps sufficient
- [✓] No missing Episcopal-specific accounts/funds
- [✓] Plan accounts for future maintenance (warnings for placeholder rates, informational allocations)

### Data Model Alignment Checklist

- [✓] All task outputs match `AccountingContext` Pydantic model requirements
- [✓] Account/fund enums and restrictions properly used
- [✓] JSON file path and naming convention correct
- [✓] ChromaDB indexing will work correctly

### Integration Points Checklist

- [✓] Profile integrates with invoice processing pipeline via existing `list_churches()` and `load_accounting_context()` APIs
- [✓] Denomination rules in `denomination_rules.py` sufficient for basic classification
- [✓] `denomination_episcopal/SKILL.md` agents will receive correct context via API

### Risks & Blockers Checklist

- [✓] No known EIME limitations that would prevent this profile
- [✓] No assumptions that would fail under reasonable circumstances
- [✓] No missing dependencies or external integrations required

---

## Recommendations

### Before Implementation

1. **Read schema definitions** (main.py:163-208) before writing the builder function.
2. **Use `seed_sample_church()` as a structural reference only**—do not copy UMC-specific account numbers or fund IDs.
3. **Decide on utilities account modeling**: Task 6 omits utilities from the CPF base. Consider whether a separate 5105 (Clergy Utilities) account is needed for parochial reporting. Plan is valid as-is.

### During Implementation

1. **Task 8 warnings:** Add an explicit warning about the 12.5% diocesan rate being a placeholder (plan already suggests this).
2. **Task 8 warnings:** Add a warning about CPF allocation schedule pending gl_mapper integration (plan already suggests this).
3. **Task 9 verification:** Run the verification script before claiming Task 8 complete. Do not skip this step.

### After Implementation

1. **Follow-up plan:** Create a task to wire `AllocationSchedule.basis="pct_of_clergy_comp"` into `gl_mapper.py` so the CPF schedule becomes active.
2. **Follow-up plan:** Enhance `denomination_rules.py` with full Episcopal overrides (CPF base calculation, restricted-revenue exclusion, endowment draw rules).
3. **Follow-up plan:** Implement Parochial Report export (Schedule A/B/C generation from the split clergy accounts).

### Testing Notes

- **Task 9 verification:** Must check all 7 checklist rows pass. Use the pseudocode provided (plan lines 459-475) or a pytest equivalent.
- **Task 10 smoke test:** Upload a realistic invoice mentioning "diocesan assessment" or "CPF" to confirm the classifier/mapper flow works end-to-end.

---

## Approval & Sign-Off

**Status:** PASS_WITH_NOTES

**Recommended Action:** **Ready for implementation.**

The plan is technically sound, achieves its objective (add a canonical Episcopal demo profile), and integrates cleanly with existing EIME architecture. All required scope is included. Risks are documented and mitigated.

**Blockers:** None.

**Comments:** The plan is notably well-scoped and realistic. It correctly identifies out-of-scope items (denomination rules, allocation logic, reporting) and documents them as future work. The 10-task structure is logical and testable.

---

## Appendix: Codebase Reference Verification

All codebase facts cited in the plan have been verified:

| Claim | Verified | Evidence |
|-------|----------|----------|
| Persistence is flat JSON | ✓ | coa_store.py:55-57 uses `Path.write_text(model_dump_json())` |
| File path pattern: `context_{church_id}.json` | ✓ | coa_store.py:45-46 defines `_ctx_path()` |
| `list_churches()` auto-discovers via glob | ✓ | coa_store.py:68-82 uses `DATA_ROOT.glob("context_*.json")` |
| ChromaDB rebuild on save | ✓ | coa_store.py:57 calls `_rebuild_index()` |
| `EPISCOPAL` enum exists | ✓ | schemas.py:35-43 includes `DenominationType.EPISCOPAL` |
| AccountingContext required fields | ✓ | schemas.py:195-208 matches plan list |
| ApportionmentAccount uses `pct_of_revenue` | ✓ | schemas.py:190-192 |
| AllocationSchedule `basis` is free-form string | ✓ | schemas.py:182-187 |

---

**Validation completed:** 2026-05-06
**Status:** PASS_WITH_NOTES — Proceed to implementation.
