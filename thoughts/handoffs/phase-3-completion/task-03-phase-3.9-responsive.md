# Task 3: Phase 3.9 Mobile Responsive UI

Status: COMPLETE

## Completed

- `_shell.html` already had the three-panel + hamburger + chat-FAB scaffolding from
  prior phases. Hardened it for FR-10.5: enlarged top-bar buttons to a 44 px touch
  target, added a mobile close (X) handle on the chat bottom sheet, tightened the
  sheet to `max-h-[80vh]`.
- `eime-shell.js` enhanced:
  - Auto-injects `<link rel="stylesheet" href="/responsive.css">` on first mount
    so any page that uses the shell inherits the responsive rules without each
    page having to remember to include them.
  - `_wireChatSwipeDismiss()` adds swipe-down-to-dismiss for the chat bottom sheet
    on `<lg` viewports (only triggers when vertical swipe > 50 px and horizontal
    drift < 60 px, so it doesn't fight scrolling).
  - Closes both nav drawer and chat sheet on Escape key when below `lg`.
- New shared stylesheet `frontend/responsive.css`:
  - `@media (max-width: 1023.98px)` block hides hardcoded `aside.w-64` /
    `aside.w-60` sidebars on legacy pages, switches the parent `flex.h-full`
    container to column flow, compresses `px-8` headers to `px-4`, collapses
    multi-column grids to a single column at `<sm` and to two columns between
    `sm` and `lg`.
  - 44 px minimum hit target for `button`, `input[type=submit]`, `select`, and
    any element with `role=button` on viewports below `lg`.
  - Tables get `display:block; overflow-x:auto; white-space:nowrap` below `md`
    so they scroll horizontally instead of clipping.
  - `html, body { max-width:100vw; overflow-x:hidden }` prevents accidental
    horizontal scroll caused by overflowing children.
  - Drawer primitives (`.eime-rsv-drawer`, `.eime-rsv-backdrop`,
    `.eime-rsv-fab`, `.eime-rsv-topbar`) used by the helper script below.
- New helper script `frontend/eime-responsive.js` for legacy pages (those that
  do **not** mount `_shell.html`):
  - Detects whether the shell is already mounted and bails out if so
    (idempotent — safe to load on every page).
  - Finds the page's hardcoded `<aside class="w-64 …">`, clones it into a
    fixed-position drawer, and injects:
      * a top bar with a hamburger button + page title + chat icon link;
      * a floating chat FAB (skipped on `chat.html` itself).
  - Wires open / close / outside-click / swipe-left / Escape / `>=1024 resize`.
- Backend: `backend/main.py` catch-all route extended to serve static assets
  with the correct `Content-Type`. Previously only `.html` was served and
  everything else fell through to the SPA-style `index.html` fallback. Added a
  small MIME-type table covering `.js / .css / .svg / .png / .woff2 / …` so
  `/responsive.css` and `/eime-responsive.js` are served with the right
  headers.
- Legacy pages updated to load the new responsive assets (CSS in `<head>`,
  JS just before `</body>`):
  - `frontend/index.html`
  - `frontend/jobs.html`
  - `frontend/budget.html`
  - `frontend/coa.html`
  - `frontend/chat.html`
  - `frontend/skills.html`
- Shell pages inherit responsive.css automatically via `eime-shell.js`
  (no per-page edit required). Verified working set:
  - `frontend/jes.html`
  - `frontend/payments.html`
  - `frontend/knowledge-base.html`
  - `frontend/treasurer-queue.html`
  - `frontend/settings/approval-chains.html`
  - `frontend/settings/model-config.html`

## Code Changes

Created:
- `/Users/erichillerbrand/chart of accounts/frontend/responsive.css`
- `/Users/erichillerbrand/chart of accounts/frontend/eime-responsive.js`
- `/Users/erichillerbrand/chart of accounts/backend/tests/test_phase3_9_responsive.py`

Modified:
- `/Users/erichillerbrand/chart of accounts/frontend/_shell.html`
  (mobile top-bar buttons -> 44 px touch targets, chat sheet close button,
  `max-h-[80vh]`)
- `/Users/erichillerbrand/chart of accounts/frontend/eime-shell.js`
  (auto-inject responsive.css, swipe-to-dismiss chat sheet, Escape closes
  drawers)
- `/Users/erichillerbrand/chart of accounts/frontend/index.html` (link + script)
- `/Users/erichillerbrand/chart of accounts/frontend/jobs.html` (link + script)
- `/Users/erichillerbrand/chart of accounts/frontend/budget.html` (link + script)
- `/Users/erichillerbrand/chart of accounts/frontend/coa.html` (link + script)
- `/Users/erichillerbrand/chart of accounts/frontend/chat.html` (link + script)
- `/Users/erichillerbrand/chart of accounts/frontend/skills.html` (link + script)
- `/Users/erichillerbrand/chart of accounts/backend/main.py` (static MIME-type
  table; catch-all serves `.js`, `.css`, fonts, images with correct Content-Type)

## Tests

`backend/tests/test_phase3_9_responsive.py` — 36 tests, all passing:

```
36 passed, 4 warnings in 7.83s
```

Coverage:
- Static-asset routing: `/responsive.css`, `/eime-shell.js`,
  `/eime-responsive.js` served with correct MIME types.
- Shell HTML structure: lg: breakpoints, mobile chat FAB, nav backdrop,
  chat backdrop, 44 px touch targets present.
- Shell JS behavior: `_adjustToBreakpoint`, `toggleNav`, `toggleChat`,
  responsive.css auto-injection, swipe handling, Escape-key wiring.
- Per-page parametric tests: each of the 6 legacy pages includes
  `/responsive.css`, `/eime-responsive.js`, and a viewport meta tag.
- responsive.css contents: collapses legacy sidebar, has 44 px touch target,
  prevents horizontal scroll, exposes drawer primitives.
- eime-responsive.js behavior: clones legacy sidebar, isShellPage guard,
  touch and Escape wiring, chat-FAB skip on chat.html.
- All 6 shell pages return 200 and call `EIMEShell.mount`.

Regression: ran prior-phase suites
(`test_phase1_pipeline.py + test_phase3_recurring.py + test_recurring_store_and_csv.py`)
— **24 passed**, no regressions from the static-MIME-table backend change.

## Viewport Testing

Static / structural verification (no headless browser available in this
environment — Playwright not installed):

- Mobile 375 px: VERIFIED via CSS rules.
  - `aside.w-64` + `aside.w-60` set to `display:none !important` below 1024 px.
  - `html, body { max-width:100vw; overflow-x:hidden }` prevents horizontal
    scroll.
  - All buttons/selects/role=button get `min-height: 44px` below 1024 px.
  - Tables fall back to `display:block; overflow-x:auto`.
  - Drawer + chat FAB visible (`.eime-rsv-topbar` + `.eime-rsv-fab` flip from
    `display:none` to `display:flex` at the breakpoint).
- Tablet 768 px: VERIFIED via CSS rules.
  - Hamburger drawer pattern still active (`<lg`).
  - Two-column grids restored between `sm` and `lg`.
  - Chat is bottom-sheet via the existing `_shell.html` rules.
- Desktop 1280 px: VERIFIED via CSS rules.
  - `aside.w-64` / `aside.w-60` revert to default `display:block` (no rule
    overrides `>=lg`).
  - `flex-direction: row` is the natural Tailwind state.
  - `.eime-rsv-topbar`, `.eime-rsv-fab`, `.eime-rsv-drawer` stay
    `display:none` (rule scoped to `<lg`).

For full visual cross-device sign-off (real iPhone + iPad form factors)
manual QA is recommended — see "Issues" below.

## Issues

- **No real-browser QA in CI yet.** Playwright is not installed in this
  environment, so the new tests are static-asset assertions, not actual
  viewport pixel checks. Phase 3.10 (or a separate "browser CI" task) should
  add Playwright, target 375 / 768 / 1280 px, and verify (a) drawer slides
  open / closed, (b) bottom sheet swipe-dismisses, (c) document.documentElement
  width never exceeds viewport width.
- **Legacy pages keep their hardcoded sidebar markup**, even though it's hidden
  below `lg`. A follow-up refactor migrating `index.html`, `jobs.html`,
  `budget.html`, `coa.html`, `chat.html`, `skills.html` to mount via
  `_shell.html` (like `jes.html` does) would let us delete the
  `eime-responsive.js` shim entirely. Not a blocker for FR-10.5.
- **Tailwind CDN reflow.** Pages that load Tailwind via `cdn.tailwindcss.com`
  ship un-purged CSS to the browser. Mobile devices on 3G will see a brief
  unstyled-content flash. Switching to a build-time Tailwind purge is out of
  scope but worth considering during Phase 4 hardening.
- **Pre-existing test issues (unchanged from Task 2):** `test_phase3_recon.py`
  imports a non-existent `backend.tools.recon_matcher` (untracked file from
  Phase 3.6), and `test_budget_schemas.py::test_existing_context_loads_without_budget`
  fails due to fixture ordering. Neither is touched by this task.

## Next Task

Phase 3.10: Non-Functional Hardening (RBAC, Audit Log, ACS Gate, Model Config)
