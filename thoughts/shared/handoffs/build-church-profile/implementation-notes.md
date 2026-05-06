# Holy Comforter Episcopal Church Profile - Implementation Notes

**Started:** 2026-05-06
**Completed:** 2026-05-06
**Plan:** thoughts/shared/plans/PLAN-holy-comforter-episcopal.md
**Implementer:** kraken agent
**Status:** COMPLETE

## Checkpoints
**Task:** Implement Holy Comforter Episcopal Church profile (10 tasks)

### Phase Status
- Task 1 (Funds, 6 funds): VALIDATED
- Task 2 (Asset/Liability/Net-Asset Accounts, 21 accts): VALIDATED
- Task 3 (Revenue Accounts, 9 accts): VALIDATED
- Task 4 (Personnel Expenses w/ Parochial split, 15 accts): VALIDATED
- Task 5 (Ministry/Facility/Admin Expenses, 28 accts): VALIDATED
- Task 6 (CPF Allocation Schedule CPF_18PCT): VALIDATED
- Task 7 (Diocesan Apportionment 8410 @ 12.5%): VALIDATED
- Task 8 (Assemble & Persist as context_holy_comforter.json): VALIDATED
- Task 9 (Episcopal Coverage 12-point checklist): PASSED
- Task 10 (E2E Smoke Test - API + semantic_search): PASSED

### Validation State
```json
{
  "accounts_total": 73,
  "funds_total": 6,
  "schedules_total": 1,
  "apportionments_total": 1,
  "warnings_recorded": 2,
  "json_file": "backend/data/context_holy_comforter.json",
  "json_size_bytes": 20694,
  "chromadb_collection": "coa_holy_comforter",
  "list_churches_visible": true,
  "api_endpoints_passing": 5
}
```

## Artifacts Created/Modified

### Modified
- `backend/tools/coa_store.py` - added `seed_holy_comforter()` builder; extended `ensure_seed()` to call it idempotently

### Created
- `backend/data/context_holy_comforter.json` - persisted Pydantic-validated AccountingContext (697 lines, 20.7 KB)
- `backend/data/_verify_holy_comforter.py` - 12-check Episcopal coverage validation script
- `backend/data/chroma/<uuid>/` - ChromaDB collection `coa_holy_comforter` (auto-rebuilt by `_rebuild_index`)

## Validation Summary

### Task 9 - Structural Coverage (12/12 PASS)
- [x] Diocesan Assessment (8410 + ApportionmentAccount)
- [x] National Church Pledge (8420)
- [x] CPF mandatory 18% (5210 + CPF_18PCT schedule + 2040 liability)
- [x] Rector's Discretionary (RECTOR_DISC BOARD_DESIGNATED + 4900/6900/1040)
- [x] Endowment principal/income split (ENDOW_PRIN + ENDOW_INC + 1900/1910/3300/3310)
- [x] Parochial Report clergy split (5100, 5101, 5210, 5220 all present)
- [x] All restriction classes represented (WITHOUT, PURPOSE, PERMANENT)
- [x] BOARD_DESIGNATED category present (RECTOR_DISC)
- [x] Account-fund restriction class consistency (all 73 accounts)
- [x] Account number uniqueness (73/73)
- [x] RECTOR_DISC linkage on revenue/expense pair (4900 & 6900)
- [x] Endowment income (4300) -> ENDOW_INC; principal (1900) -> ENDOW_PRIN

### Task 10 - API + Semantic Smoke Tests (all PASS)
- GET /api/churches returns Holy Comforter (denomination=EPISCOPAL)
- GET /api/churches/holy_comforter/context returns full COA (73/6)
- GET /api/churches/holy_comforter/accounts returns 73 accounts
- GET /api/churches/holy_comforter/funds returns 6 funds incl. RECTOR_DISC, ENDOW_PRIN, ENDOW_INC
- GET /api/churches/holy_comforter/search?q=CPF+pension returns 5210 as top-1
- Semantic search verified for: CPF pension, diocesan assessment, rector discretionary, endowment income distributions, altar guild communion, episcopal relief development (all return expected target as top-1)

### Notes / Caveats
- The MiniLM-L6-v2 embedding does not surface 5210 in top-3 for the loose query "clergy pension" (without "CPF"); this is an embedding-model limitation, not a profile defect. Direct queries naming "CPF" or "pension assessment" work cleanly.
- 2 warnings persisted in the AccountingContext warning the user that:
  1. Diocesan assessment rate 12.5% is a placeholder
  2. CPF allocation schedule basis "pct_of_clergy_comp" is not yet wired into gl_mapper
