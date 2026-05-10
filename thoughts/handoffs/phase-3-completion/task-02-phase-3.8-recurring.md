# Task 2: Phase 3.8 Recurring Entries + Batch CSV

Status: COMPLETE

## Completed

- RecurringJE schema extended with `updated_at` and `draft_count`
  (`backend/models/schemas.py:648-661`).
- New helper module `backend/tools/recurring_store.py` with full CRUD
  (`load_recurring_entries`, `save_recurring_entries`, `find_recurring`,
  `create_recurring`, `update_recurring`, `delete_recurring`,
  `get_due_for_drafting`, `calculate_next_cron`, `list_all_church_ids`).
- New helper module `backend/tools/je_csv_importer.py` exposing
  `parse_je_csv` and `import_je_csv` with `ImportResult` dataclass.
  Validates required columns (`memo, from_account, to_account, amount,
  fund`), positive amounts, optional `date` column (YYYY-MM-DD), and
  GL/fund codes against the church COA when one is loaded.
- `backend/scheduler.py::draft_recurring_jes` now bumps `draft_count`
  and recomputes `next_run` via `calculate_next_cron` (croniter-backed).
  Nightly cron job already registered at 02:00 in `start_scheduler`.
- `backend/main.py` endpoints refactored to delegate to the helpers:
  - POST `/api/jes/recurring`
  - GET `/api/jes/recurring?church_id=...`
  - PUT `/api/jes/recurring/{recurring_id}` (cron, active, template_je)
  - DELETE `/api/jes/recurring/{recurring_id}` (hard delete via store)
  - POST `/api/jes/import-csv` (multipart `file` + form `church_id`,
    optional `created_by`).
- `croniter>=2.0.0` added to `pyproject.toml`; `uv sync` confirmed
  `croniter==6.2.2` installed.
- Frontend: `frontend/jes.html` gains a Recurring tab (list, pause /
  resume, edit cron, delete) and an Import CSV button with success +
  per-row error toast.

## Code Changes

Created:
- `/Users/erichillerbrand/chart of accounts/backend/tools/recurring_store.py`
- `/Users/erichillerbrand/chart of accounts/backend/tools/je_csv_importer.py`
- `/Users/erichillerbrand/chart of accounts/backend/tests/test_recurring_store_and_csv.py`

Modified:
- `/Users/erichillerbrand/chart of accounts/backend/models/schemas.py`
  (RecurringJE: added `updated_at`, `draft_count`)
- `/Users/erichillerbrand/chart of accounts/backend/scheduler.py`
  (recompute `next_run`, increment `draft_count`)
- `/Users/erichillerbrand/chart of accounts/backend/main.py`
  (5 recurring/CSV endpoints rewritten to call helper modules)
- `/Users/erichillerbrand/chart of accounts/frontend/jes.html`
  (Recurring tab, Import CSV button, action handlers)
- `/Users/erichillerbrand/chart of accounts/pyproject.toml`
  (added `croniter>=2.0.0`)

Pre-existing (unchanged): `backend/scheduler.py::start_scheduler` already
registered the 02:00 nightly job before this task.

## Tests

All Phase 3.8 tests pass:

```
backend/tests/test_phase3_recurring.py ......          [ 6/6 PASS]
backend/tests/test_recurring_store_and_csv.py ........ [ 8/8 PASS]
                                                      14 passed
```

New test coverage in `test_recurring_store_and_csv.py`:
- `test_calculate_next_cron_returns_future` — croniter integration
- `test_create_load_update_delete_recurring` — store CRUD round-trip
- `test_get_due_for_drafting` — active + past `next_run` filter
- `test_parse_je_csv_happy_path`
- `test_parse_je_csv_missing_column` — header validation
- `test_parse_je_csv_bad_amount` — per-row validation, error reporting
- `test_import_je_csv_persists` — file write verified
- `test_import_je_csv_with_optional_date` — optional `date` column

Full backend suite (excluding pre-existing untracked broken file
`test_phase3_recon.py` which imports a non-existent
`backend.tools.recon_matcher`): **156 passed, 1 failed**. The single
failure (`test_budget_schemas.py::test_existing_context_loads_without_budget`)
is a pre-existing fixture-ordering issue unrelated to Phase 3.8 — the
Holy Comforter context now has a budget loaded by an earlier test, so
the assertion `ctx.budget is None` fails.

## Issues

- COA validation in `je_csv_importer._load_coa_codes` is duck-typed
  against `AccountingContext.accounts` / `funds` — it tolerates both
  attribute and dict access so unseeded test churches simply skip
  validation. Production churches must be seeded for strict GL-code
  enforcement to kick in.
- `RecurringJE.template_je` remains a `Dict[str, Any]` rather than a
  nested `JournalEntry` model to avoid coupling persistence format to
  Decimal/date serialization quirks; the create endpoint validates the
  template shape via `JournalEntry(**template)` before persisting.
- Pre-existing `test_phase3_recon.py` (untracked) cannot import
  `backend.tools.recon_matcher`. Out of scope for this task; flagged for
  whoever owns Phase 3.6.

## Next Task

Phase 3.9: Mobile Responsive UI
