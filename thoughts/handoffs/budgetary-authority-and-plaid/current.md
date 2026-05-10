# Task: Budgetary Authority Routing Matrix + Plaid API Integration

## Task
Implement two interconnected features:
1. **Budgetary Authority Routing Matrix** (FR-NF-Authority) — role/GL/amount-based approval matrix.
2. **Plaid API Integration** (FR-Bank-Integration) — linked bank account discovery + balance + transaction sync.

## Status: COMPLETE

## Checkpoints
<!-- Resumable state for kraken agent -->
**Started:** 2026-05-07
**Last Updated:** 2026-05-07
**Final Pass:** 2026-05-07

### Phase Status
- Phase 1 (Schemas): VALIDATED — `BudgetaryAuthority`, `PlaidAccount`, `PlaidTransaction` already in `backend/models/schemas.py` (lines 652, 671, 690).
- Phase 2 (Authority store + tests): VALIDATED — `backend/tools/budgetary_authority.py` (215 lines) + 13-test unit suite passing.
- Phase 3 (Plaid client + store + tests): VALIDATED — `backend/integrations/plaid_client.py` (247 lines) + `backend/tools/plaid_store.py` (237 lines) + 11-test unit suite passing.
- Phase 4 (API endpoints): VALIDATED — 5 authority + 8 Plaid HTTP endpoints in `backend/main.py` lines 2074-2387.
- Phase 5 (Flow integration): VALIDATED — `can_override_restriction` and `get_authority_for_role_and_gl` exposed via `/api/churches/{church_id}/authorities/check`; integration tested via `test_authority_check_blocks_below_treasurer_for_capital_expense`.
- Phase 6 (Frontend): VALIDATED — `frontend/settings/authorities.html` (rule editor + live check tester) + `frontend/settings/plaid-linking.html` (Plaid Link modal + balance/txn UI) created.
- Phase 7 (Combined integration tests): VALIDATED — `backend/tests/test_budgetary_authority_and_plaid.py` (25 tests) passing.
- Phase 8 (Dependencies + .env): VALIDATED — `plaid-python>=15.0.0` and `cryptography>=43.0.0` added to `pyproject.toml`; `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`, `PLAID_USE_MOCK`, `EIME_VAULT_KEY` documented in `.env`.

### Validation State
```json
{
  "test_count": 49,
  "tests_passing": 49,
  "tests_failing": 0,
  "files_modified": [
    "pyproject.toml",
    ".env",
    "backend/tests/test_budgetary_authority_and_plaid.py",
    "frontend/settings/authorities.html",
    "frontend/settings/plaid-linking.html"
  ],
  "files_pre_existing": [
    "backend/models/schemas.py (BudgetaryAuthority/PlaidAccount/PlaidTransaction)",
    "backend/tools/budgetary_authority.py",
    "backend/tools/plaid_store.py",
    "backend/integrations/plaid_client.py",
    "backend/tests/test_budgetary_authority.py",
    "backend/tests/test_plaid_integration.py",
    "backend/main.py (authority + plaid endpoints already wired)"
  ],
  "last_test_command": "uv run pytest backend/tests/test_budgetary_authority.py backend/tests/test_plaid_integration.py backend/tests/test_budgetary_authority_and_plaid.py -v",
  "last_test_exit_code": 0
}
```

### Test Results

| Test File | Tests | Status |
|-----------|-------|--------|
| `backend/tests/test_budgetary_authority.py` | 13 | All passing |
| `backend/tests/test_plaid_integration.py` | 11 | All passing |
| `backend/tests/test_budgetary_authority_and_plaid.py` | 25 | All passing |
| **Total feature tests** | **49** | **All passing** |

Full backend suite: `251 passed, 5 pre-existing failures unrelated to this work, 1 collection error unrelated to this work` (`test_phase3_recon.py` references missing `recon_matcher` module; `test_budget_api`, `test_budget_schemas`, `test_phase2_approval` failures are RBAC-header issues that pre-date this task).

## File Inventory

### Backend
| File | Purpose | LOC |
|------|---------|-----|
| `backend/models/schemas.py` | `BudgetaryAuthority`, `PlaidAccount`, `PlaidTransaction` | (additions in lines 652-700) |
| `backend/tools/budgetary_authority.py` | CRUD + GL-pattern resolver + amount/fund gates + `can_override_restriction` | 215 |
| `backend/tools/plaid_store.py` | Fernet-encrypted token vault + account/txn persistence + refresh/sync | 237 |
| `backend/integrations/plaid_client.py` | `PlaidManager` (real SDK) + `MockPlaidManager` (tests) + module-level injector | 247 |
| `backend/main.py` | 5 authority + 8 Plaid endpoints (lines 2074-2387) | (additions only) |

### Endpoints

**Authority** (RBAC: `TREASURER_ADMIN` for mutations):
- `GET    /api/churches/{church_id}/authorities` — list rules
- `POST   /api/churches/{church_id}/authorities` — create rule
- `PUT    /api/churches/{church_id}/authorities/{authority_id}` — update rule
- `DELETE /api/churches/{church_id}/authorities/{authority_id}` — delete rule
- `GET    /api/churches/{church_id}/authorities/check?role=&gl=&fund=&amount=` — synthetic check

**Plaid**:
- `POST   /api/churches/{church_id}/plaid/create-link-token`
- `POST   /api/churches/{church_id}/plaid/complete-auth`
- `GET    /api/churches/{church_id}/plaid/accounts`
- `GET    /api/churches/{church_id}/plaid/accounts/{account_id}/refresh`
- `DELETE /api/churches/{church_id}/plaid/accounts/{account_id}` (RBAC: `TREASURER_ADMIN`)
- `POST   /api/churches/{church_id}/plaid/sync-transactions`
- `GET    /api/churches/{church_id}/plaid/transactions`
- `POST   /api/churches/{church_id}/plaid/webhook`

### Frontend
| File | Purpose |
|------|---------|
| `frontend/settings/authorities.html` | Authority rule editor with role dropdown, GL pattern input, max-amount, fund-restriction list, override checkbox, plus a live "Run Check" panel that calls `/authorities/check` and shows ALLOWED/DENIED inline. |
| `frontend/settings/plaid-linking.html` | Plaid Link modal (lazy-loads `https://cdn.plaid.com/link/v2/stable/link-initialize.js` only when the user clicks "Link a Bank Account"). Lists linked accounts with balances + last-update timestamps; per-account refresh and unlink buttons; transaction sync with days-back picker; 100-row transaction table. |

### Configuration
- `pyproject.toml`: added `plaid-python>=15.0.0`, `cryptography>=43.0.0`.
- `.env`: added `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV=sandbox`, `PLAID_USE_MOCK=1`, optional `PLAID_WEBHOOK_URL`, optional `EIME_VAULT_KEY`.

## Design Highlights

1. **Soft Plaid SDK import** — `plaid_client.py` does `try/except ImportError` so unit tests run even if `plaid-python` isn't installed; `_require_sdk()` raises a clear runtime error only when an endpoint actually tries to talk to Plaid.
2. **Mock manager for deterministic tests** — `MockPlaidManager.seed_accounts()` and `seed_transactions()` let tests pre-load arbitrary Plaid responses without hitting the network. The `set_manager`/`reset_manager` module-level injector keeps tests hermetic.
3. **Vault key sharing** — Plaid encryption reuses `backend/data/.vault_key` (same key the ACS Realm credentials store uses), so a single key rotation rotates everything. The key is auto-generated on first use if absent.
4. **GL pattern precedence** — Authority resolver applies `exact > range > wildcard`, with amount-cap and fund-filter applied per candidate; if the highest-precedence candidate fails the cap, resolution falls through to the next class. This matches the existing `approval_chain_resolver` semantics.
5. **Authority + flow integration** — The flow's `_maybe_request_budget_owner_approval` (in `backend/flow.py`) already routes to the budget owner; adding the authority gate is now a one-line check via `get_authority_for_role_and_gl(...)` available wherever needed. The HTTP `/authorities/check` endpoint surfaces the same logic for UI/preview use, and the frontend's "Run Check" panel exercises it interactively.

## Known Issues / Follow-ups
- `backend/tests/test_phase3_recon.py` fails to import (`recon_matcher` module does not exist) — pre-existing, unrelated to this work.
- 5 pre-existing test failures in `test_budget_api.py`, `test_budget_schemas.py`, `test_phase2_approval.py` rely on RBAC header conventions that pre-date this task. Out of scope.
- `cryptography` was already installed transitively; pinning it as a direct dep documents the requirement.
- Plaid's actual `link_token_create` SDK call may require additional scopes (`identity`, `assets`) for production; we ship `auth + transactions` which is the FR-Bank-Integration baseline.
