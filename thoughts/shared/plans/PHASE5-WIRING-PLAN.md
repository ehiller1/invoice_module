# Phase 5: Database Layer Integration — Wiring Plan
Created: 2026-05-09
Author: architect-agent
Status: Draft

## Overview

Phase 4 delivered 22 tables and 11 store modules. Phase 5 finishes routing every
runtime read/write through those stores, removes JSONL/in-memory holdouts, and
wraps multi-row updates in `atomic_transaction()`. The good news from the audit:
**most endpoints are already wired**. This plan targets the residual file-based
holdouts and tightens transaction boundaries.

## Current Wiring Audit (✓ VERIFIED by reading source)

### Already DB-backed
| Subsystem | Module | Verification |
|-----------|--------|--------------|
| Churches / COA / Funds / Budget / YTD | `db.coa_store` (aliased as `coa_store`) | `main.py:46`, `main.py:131-682` all call `coa_store.*` |
| Manual JE create/list | `db.journal_entry_store` | `main.py:898, 912` |
| JE find/update/transition/post/list | `db.journal_entry_store` | `main.py:1339-1391, 1480-1583` |
| Processing jobs (entire pipeline) | `db.processing_job_store` | `flow.py:54-108` (`get_job/list_jobs/_persist_job/_update_job/create_job`) |
| Decision ledger | `db.decision_ledger_store` | `flow.py:40-51` |
| Payments (create/update/get/list/find_by_je) | `db.payment_store` | `main.py:1615, 1721, 1781` |
| Vendors | `db.vendor_store` | `main.py:1643, 1651` + vendor CRUD endpoints `1853-1916` |
| Plaid accounts/transactions | `db.plaid_store` | `main.py:2459` |
| Approval chains (per-church config) | `db.approval_store` | imported `main.py:63` |
| Bank statements upload | `db.bank_txn_store` | imported `main.py:64` |
| Recon: matching + save | `db.recon_store` | `main.py:2472, 2489, 2500` |

### File-based / In-memory HOLDOUTS (target of this plan)

| Holdout | Location | Replacement |
|---------|----------|-------------|
| `_persist_je()` (legacy JSONL writer) | `main.py:852-861` | DELETE — superseded by `journal_entry_store.create_journal_entry` |
| `_persist_payment()` (legacy JSONL writer) | `main.py:1586-1596` | DELETE — superseded by `payment_store.create_payment` |
| `_load_payments()` (legacy JSONL reader) | `main.py:1598-1611` | DELETE — superseded by `payment_store.list_payments` |
| `_load_recon_matches/_save_recon_matches/_recon_matches_path` | `main.py:2431-2450` | Replace caller at `main.py:2396` (in `auto_match`) with `recon_store.load_matches` / `save_match` (already used downstream at `2467, 2500`) |
| Recurring JE storage (entire feature) | `main.py:1914-2027` (`_recurring_path`, `_load_recurring`, `_persist_recurring`, `tools.recurring_store`) | New `db.recurring_je_store` (Phase 5b — see Risk section) |
| `tools.approval_audit` (JSONL hash chain) | `tools/approval_audit.py` | Forward all calls to `db.approval_audit_store` (drop-in shim, schema already exists) |
| `JE_DATA_DIR / PAYMENT_DATA_DIR / RECURRING_DATA_DIR` (Path roots) | `main.py:849, 1583, 1914` | Remove once dependent helpers removed |

## Endpoint → Store Mapping (target state)

| Endpoint (`main.py`) | Line | Store(s) |
|----------------------|------|----------|
| `POST /api/jes/manual-create` | 864 | `journal_entry_store.create_journal_entry` |
| `GET  /api/churches/{id}/jes/manual` | 909 | `journal_entry_store.list_journal_entries` |
| `POST /api/jes/{id}/post` | 1396 | `journal_entry_store` (load+update); after success, `coa_store.update_ytd_actual` (per debit/credit line, optimistic-locked) |
| `POST /api/jes/{id}/transition` | 1480 | `journal_entry_store.transition_je_status` (wrap in `atomic_transaction`) |
| `GET  /api/jes` | 1511 | `journal_entry_store.list_journal_entries` |
| `POST /api/jes/{id}/payment` | 1632 | `payment_store.create_payment` + `journal_entry_store.update_journal_entry` (atomic) + `approval_audit_store.append_event` |
| `POST /api/payments/{id}/approve` | 1741 | `payment_store.update_payment` + `approval_audit_store.append_event` (atomic) |
| `GET  /api/payments/{id}/ach-file` | 1799 | `payment_store.get_payment` |
| `GET  /api/payments/{id}/check-pdf` | 1820 | `payment_store.get_payment` |
| `GET  /api/churches/{id}/payments` | 1844 | `payment_store.list_payments` |
| `POST /api/invoice/upload` | 687 | `processing_job_store.create_job` (via `flow.create_job`) |
| `GET  /api/jobs/{id}` / `GET /api/jobs` | 707, 715 | `processing_job_store.get_job/list_jobs` |
| `POST /api/jobs/{id}/hitl` | 739 | `processing_job_store.update_job` (via `flow._update_job`) + `approval_audit_store.append_event` |
| `POST /api/jobs/{id}/treasurer-decision` | 1187 | `processing_job_store.update_job` + `approval_audit_store.append_event` (line 1228) |
| `GET  /api/approve` (token approval) | 1099 | `processing_job_store` + `approval_audit_store.append_event` (line 1147) |
| `GET  /api/churches/{id}/audit/approvals` | 1248 | `approval_audit_store.list_events` |
| `GET  /api/audit-chain/verify` | 2051 | `approval_audit_store.verify_chain` |
| `GET  /api/churches/{id}/decision-ledger` | 1302 | `decision_ledger_store.get_ledger` |
| `GET  /api/coa` / `/api/coa/search` / `/api/budget/variance` | 2562, 2633, 2664 | `coa_store.*` |
| `PUT  /api/churches/{id}/budget/ytd-reset` | 571 | `coa_store.reset_ytd_actuals` (atomic) |
| `POST /api/churches/{id}/budget/year-end-reset` | 615 | `coa_store.save_accounting_context` + `reset_ytd_actuals` (atomic) |
| `GET  /api/churches/{id}/budget/variance-report` | 510 | `coa_store.get_budget_variance` (replace local computation) |
| `POST /api/churches/{id}/plaid/sync-transactions` | 2354 | `plaid_store.upsert_transactions` |
| `POST /api/churches/{id}/plaid/auto-match` | 2451 | `recon_store.find_matching_entries` + `recon_store.save_match` (replace `_load_recon_matches` at 2396) |
| `POST /api/churches/{id}/bank-statements/upload` | 2522 | `bank_txn_store.bulk_insert` |
| `*/vendors/*` (5 endpoints) | 1853-1916 | `vendor_store.*` |
| `*/approval-chains/*` (4 endpoints) | 1035-1098 | `approval_store.*` |
| `*/authorities/*` (4 endpoints) | 2116-2231 | `approval_store.*` (budgetary authority) |

## Phased Implementation

### Phase 5a — Eliminate confirmed dead JSONL helpers (Small, ~1 hr)
**Files to modify:**
- `backend/main.py`
  - DELETE `_jes_path`, `_persist_je` (lines 852-861) — no callers (✓ verified by grep)
  - DELETE `_payments_path`, `_persist_payment`, `_load_payments`, `_find_payment` body simplification (1586-1611) — `_find_payment` is still used (line 1763, 1805); reduce its body to a thin wrapper around `payment_store.get_payment` (already mostly done, line 1615)
  - DELETE `JE_DATA_DIR` constant (849) once unused

**Acceptance:**
- [ ] No remaining `*.jsonl` write paths in JE/payment endpoints
- [ ] Existing E2E tests still pass (`backend/tests/`)

### Phase 5b — Migrate `_load_recon_matches` caller (Small, ~30 min)
**File:** `backend/main.py:2391-2450`
- Replace `matches = _load_recon_matches(church_id)` at line 2396 with `matches = recon_store.load_matches(church_id)`
- DELETE `_recon_matches_path`, `_load_recon_matches`, `_save_recon_matches` (2431-2450)

**Acceptance:**
- [ ] `auto_match` endpoint still returns same shape
- [ ] No `recon_matches_*.json` files written under `backend/data/`

### Phase 5c — Approval audit shim → DB (Medium, ~2 hrs)
**Strategy:** keep the `tools.approval_audit` import surface stable, swap implementation.

**File:** `backend/tools/approval_audit.py`
- Rewrite `append_event/list_events/verify_chain/get_event` as one-line forwards to `db.approval_audit_store`
- Hash-chain semantics already implemented in `db.approval_audit_store.append_event` (`_compute_hash` at line 23, chain verify at 159)
- Delete JSONL filesystem code (`_store_path`, `_last_hash`, `DATA_DIR`)

**Migration:** existing `backend/data/approvals_*.jsonl` → DB via `db/migrate_from_files.py` (already exists per Phase 4 deliverables; verify it covers approvals).

**Acceptance:**
- [ ] `approval_audit.append_event` writes to `approval_audit_events` table only
- [ ] `verify_chain` returns True against migrated history
- [ ] `audit-chain/verify` endpoint (`main.py:2051`) returns valid

### Phase 5d — Recurring JE store (Medium, ~3 hrs)
**Currently:** `backend/data/recurring_*.jsonl` via `tools.recurring_store` and `main.py:1914-2027` helpers.

**Action:**
1. Create `backend/db/recurring_je_store.py` mirroring `journal_entry_store.py` pattern
2. Add `recurring_journal_entries` table to `schema.sql` (if not already present from Phase 4 — VERIFY)
3. Replace endpoints `1947, 1982, 1993, 2018` to call new store
4. Delete `_recurring_path`, `_load_recurring`, `_persist_recurring` (1914-1945) and the `RECURRING_DATA_DIR` override at 1968, 1996, 2021

**Acceptance:**
- [ ] Schedule-driven recurring JE generation continues to work (scheduler.py)
- [ ] Test in `backend/tests/` covering recurring CRUD passes against DB

### Phase 5e — Atomic transaction boundaries (Medium, ~2 hrs)

Wrap the following multi-row operations in `db.transactions.atomic_transaction()`:

| Operation | Site | Why |
|-----------|------|-----|
| Post JE → ACS + update YTD per line | `main.py:1396-1461` | Posting must be all-or-nothing across JE row + every `update_ytd_actual` call |
| Create payment for JE + flip JE status | `main.py:1632-1740` | JE.status DRAFT→PENDING_PAYMENT and payment row insertion must commit together |
| Approve payment + audit event | `main.py:1741-1798` | payment status flip + hash-chained audit event must be atomic |
| Treasurer decision | `main.py:1187-1247` | job state mutation + audit event |
| HITL submit | `main.py:739-779` → `flow.submit_hitl_decisions` | job mutation + ledger append + (potentially) JE creation |
| `_build_and_emit` JE creation + YTD update + audit event | `flow.py:567+` and `flow.py:633` | Critical pipeline atomicity |
| YTD reset | `main.py:571-614` | Many account rows reset together |
| Year-end reset | `main.py:615-658` | Context save + YTD reset |
| Bank statement upload bulk insert | `main.py:2522-2561` | Bulk inserts |

**Pattern:**
```python
from .db.transactions import atomic_transaction
with atomic_transaction() as conn:
    payment_store.create_payment(church_id, inst, conn=conn)
    journal_entry_store.update_journal_entry(je.entry_id, {"status": "PENDING_PAYMENT"}, conn=conn)
    approval_audit_store.append_event(church_id, {...}, conn=conn)
```
**NOTE:** stores currently take their own connections. Phase 5e includes adding optional `conn=` kwarg to each store method to participate in an outer transaction.

### Phase 5f — Optimistic locking on YTD (Small, ~1 hr)
**Currently:** `coa_store.update_ytd_actual` at `coa_store.py:567` (per audit). The pipeline calls it from `flow.py:633`.

**Action:**
- Confirm `update_ytd_actual` uses `WHERE version = :expected_version` and bumps version
- Add retry loop in caller (3 attempts, exponential backoff 50ms/100ms/200ms) on `OptimisticLockError`
- On final failure: mark job as `FAILED_LOCK_CONTENTION`, surface for manual replay

### Phase 5g — Error handling & monitoring (Small, ~1 hr)
- Replace any remaining file-based error recovery with DB queries (`processing_job_store.list_jobs(status='FAILED')`)
- Add `tldr diagnostics backend/` to CI gate
- Log structured events on lock retry, audit-chain verify failure, atomic rollback

## Data Flow Diagrams

### Before (residual JSONL) — Recurring JE
```
client → POST /api/jes/recurring
       → tools.recurring_store (sets DATA_DIR)
       → backend/data/recurring_<church>.jsonl  (append)
```

### After
```
client → POST /api/jes/recurring
       → db.recurring_je_store.create_recurring(church_id, je)
       → atomic_transaction:
           INSERT recurring_journal_entries
           INSERT approval_audit_events  (kind=RECURRING_CREATED)
       → return entry_id
```

### Before — Payment approval (already DB, but not atomic)
```
approve_payment → payment_store.update_payment(status=APPROVED)
               → approval_audit.append_event   (separate connection)
               → returns even if audit fails silently
```

### After — Payment approval (atomic)
```
approve_payment → with atomic_transaction() as conn:
                    payment_store.update_payment(..., conn=conn)
                    approval_audit_store.append_event(..., conn=conn)
                  → both commit or both rollback
```

## Audit Trail Integration

**Hash chain:** `db.approval_audit_store._compute_hash` (line 23) computes
`sha256(prev_hash || canonical_json(event))`. Within a single church, events are
serialized by row insertion order; we must take a row-level lock on the latest
event per `church_pk` while computing the new hash to avoid two concurrent
appenders racing against the same `prev_hash`.

**Required event captures (verified existing call sites):**
| Site | Event kind | actor | rationale |
|------|------------|-------|-----------|
| `main.py:1147` token approve | `BUDGET_OWNER_APPROVAL` | email principal | from request |
| `main.py:1228` treasurer decision | `TREASURER_DECISION` | session user | from body |
| `main.py:1725` payment created | `PAYMENT_CREATED` | session user | "auto" |
| `main.py:1788` payment approved | `PAYMENT_APPROVED` | session user | from body |

**To add:**
| Site | Event kind |
|------|------------|
| JE post (`main.py:1396`) | `JE_POSTED_TO_ACS` |
| JE manual create (`main.py:864`) | `JE_DRAFTED` |
| Recurring JE create (5d) | `RECURRING_CREATED` |
| YTD reset (`main.py:571`) | `YTD_RESET` |
| Year-end reset (`main.py:615`) | `YEAR_END_ROLLOVER` |

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `recurring_journal_entries` table not in Phase 4 schema | Blocks 5d | Verify with `grep recurring backend/db/schema.sql`; add migration if absent |
| Stores don't accept `conn=` kwarg today | Blocks 5e atomic wrapping | Phase 5e includes the threading work; until then, accept best-effort serial commits + idempotent retry |
| Hash chain race on concurrent appenders | Two events with same `prev_hash` → broken chain | `SELECT ... FOR UPDATE` on latest event row inside `append_event` |
| YTD optimistic-lock contention under heavy posting | JE post spuriously fails | 3-attempt retry with backoff; surface `FAILED_LOCK_CONTENTION` for replay |
| Migration of legacy JSONL approvals | Lost audit history if mis-migrated | Run `migrate_from_files.py` in dry-run, diff event counts, then live |
| `tools.approval_audit` shim breaks callers passing `Path` | Import-site failures | Keep signature identical; only rewrite body |
| Tests rely on `JE_DATA_DIR` / `RECURRING_DATA_DIR` env overrides | Test red on 5a/5d | Provide DB-equivalent fixture (`pytest` autouse rolls back per-test transaction) |

## Open Questions

- [ ] Does `schema.sql` already define `recurring_journal_entries`? (drives 5d scope)
- [ ] Are there in-flight JSONL files in production that need migration before code removal?
- [ ] Should `_find_payment` (`main.py:1613`) survive as a `(payment, church_id)` tuple helper, or fold into store (returning church via `_resolve_church_external_id`)?
- [ ] Acceptable retry budget for YTD optimistic locking in async pipeline?

## Testing Strategy

### Unit
- Per-store: existing tests in `backend/db/tests/` — extend with `conn=` kwarg cases
- Hash chain: append 100 events concurrently, verify chain integrity

### Integration (E2E workflows)
1. **Invoice → JE → Payment → Approval**
   `POST /invoice/upload` → poll `/jobs/{id}` → `POST /jobs/{id}/hitl` → `POST /jes/{id}/payment` → `POST /payments/{id}/approve`
   Assert: 1 processing_job row, 1 journal_entry row, 1 payment row, 4 approval_audit events with valid chain
2. **YTD update under contention** — fire 10 concurrent JE posts hitting same GL account; assert all succeed via retry, final YTD = sum of all postings
3. **Atomic rollback** — inject failure into `approval_audit_store.append_event` mid-`approve_payment`; assert payment row NOT updated
4. **Recurring schedule** — create recurring JE, advance scheduler clock, assert child JE appears in `journal_entries` table
5. **Audit chain verify** — `GET /api/audit-chain/verify` returns `chain_valid=true` after 5a-5g

### Regression
- `tldr change-impact --git --run` on each phase commit
- `tldr diagnostics backend/` clean before merge

## Success Criteria

1. Zero writes to `backend/data/*.jsonl` during a full E2E run (verify with `inotifywait`/fs audit)
2. `tldr search "json.dump|\.jsonl" backend/` returns only test fixtures
3. All multi-row mutations listed in Phase 5e wrapped in `atomic_transaction`
4. `approval_audit_store.verify_chain` returns True for every church post-migration
5. Pipeline throughput equal or better than file-based baseline (no >10% regression)
6. `tldr diagnostics backend/` reports zero new errors

## Estimated Total Effort

| Phase | Effort |
|-------|--------|
| 5a — Dead helpers | 1h |
| 5b — Recon caller | 0.5h |
| 5c — Approval audit shim | 2h |
| 5d — Recurring JE store | 3h |
| 5e — Atomic transactions | 2h |
| 5f — Optimistic locking retry | 1h |
| 5g — Errors & monitoring | 1h |
| **Total** | **~10.5h** |
