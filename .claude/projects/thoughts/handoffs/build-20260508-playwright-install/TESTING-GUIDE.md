# Testing Guide: Playwright One-Click Installation

**Tests:** Manual E2E (no CI automation configured yet)  
**Duration:** ~20 min for full test, ~5 min for mocks-only test  
**Location:** `http://localhost:8000/browser-setup.html`

---

## Pre-Test Setup

### Fresh Environment
```bash
cd /Users/erichillerbrand/chart\ of\ accounts

# Option 1: Full removal (if already installed)
pip uninstall -y playwright

# Option 2: Use a fresh venv
python3 -m venv test_venv
source test_venv/bin/activate
pip install -r requirements.txt  # install everything except playwright
```

### Start Backend
```bash
# Clear mock mode
unset EIME_ACS_MOCK

# Start in reload mode for debugging
cd backend
uvicorn main:app --reload --port 8000
```

---

## Test Cases

### Test 1: Live Install (Full End-to-End)

**Precondition:** Playwright not installed

**Steps:**
1. Open `http://localhost:8000/browser-setup.html` in a browser
2. Verify Step 1 shows:
   - ⚠️ "Not Installed" for both Playwright and Chromium
   - 🌐 "Live mode" operating mode
   - 📦 "Install Playwright + Chromium" button
3. Open DevTools → Network tab
4. Click the 📦 button
5. Verify immediately:
   - Button changes to "⏳ Installing…" and is disabled
   - Log pane shows "Starting installation…"
   - Note says "Downloading Playwright (~100 MB). Do not close this tab."
6. Watch Network tab:
   - See `POST /api/integrations/acs/install` (status 200)
   - `GET /api/integrations/acs/install/status` appears every ~2 seconds
7. Watch log pane:
   - Lines from pip + playwright commands appear in real-time (within 2-3 sec of being produced)
   - Should see something like:
     ```
     $ python -m pip install playwright
     Collecting playwright
     ...
     Successfully installed playwright-...
     $ python -m playwright install chromium
     Chromium
     ...
     ```
8. Wait for completion (2-5 minutes, depending on download speed)
9. Verify on success:
   - Network tab: No more `/install/status` requests after final 200
   - Log pane: Shows complete output, scrolled to bottom
   - Button: Changes to "✅ Installed" and remains disabled
   - Note: "Installation complete. Click Next to continue."
   - Badges: Both flip from ⚠️ to ✅ (Step 1 auto-refreshed via `loadStatus()`)
   - Green banner: "All prerequisites met — ready to proceed"
   - Next button: Becomes enabled (color changes, cursor changes to pointer)
10. Click Next → Verify Step 2 loads

**Pass Criteria:**
- Install completes successfully
- Polling stops cleanly (no extra requests after success)
- Both badges update without manual refresh
- Next button automatically unlocks

---

### Test 2: Mock Mode Install

**Setup:**
```bash
# Set environment variable
export EIME_ACS_MOCK=true
# Restart backend
```

**Steps:**
1. Open `http://localhost:8000/browser-setup.html`
2. Verify Step 1 immediately shows:
   - ✅ "Installed" for both prerequisites
   - 🧪 "Mock mode" operating mode
   - **No install button visible** (entire block hidden)
   - Green "All prerequisites met" banner
   - Next button enabled

**Pass Criteria:**
- No install button appears
- Step 1 skipped directly (no UI change from existing behavior)
- Next button enabled from start

---

### Test 3: Failure Simulation

**Setup:** Edit `_run_acs_install()` in `backend/main.py` to use a bogus command:

```python
def _run_acs_install() -> None:
    """Background worker: install playwright + chromium, capture logs."""
    import subprocess, sys, datetime
    try:
        for cmd in (
            ["false"],  # ← TEMPORARY: forces exit code 1
        ):
            # ... rest unchanged ...
```

Then restart backend and test.

**Steps:**
1. Open browser to `/browser-setup.html`
2. Click install button
3. Wait ~2 seconds for first poll
4. Verify:
   - Log shows: `$ false` (command that always fails)
   - Status transitions to "error"
   - Button becomes "🔁 Retry Install" (re-enabled)
   - Note shows: "Install failed: Command failed: false (exit 1)"
   - Badges remain ⚠️
   - Next button stays disabled
5. Click "🔁 Retry Install" → repeats the flow

**Pass Criteria:**
- Error path surfaces the failure clearly
- User can retry without reloading page

---

### Test 4: Polling Stops on Completion

**During Test 1 (live install):**

1. Install succeeds
2. Open DevTools → Network tab → filter by `install/status`
3. Verify:
   - Last request shows status: "success"
   - **No further requests** (stop polling)
   - If you see continued polling, `installPollTimer` is not being cleared

**Pass Criteria:**
- Zero extra `/install/status` requests after terminal state

---

### Test 5: No Double-Polling

**During Test 1:**

1. Install is running (button disabled, log appearing)
2. Quickly click the install button (even though it's disabled)
3. No-op expected (second button click blocked by `disabled` attribute)
4. Watch Network tab: Only one polling chain (one request every 2s, not two)

**Pass Criteria:**
- Single polling chain even if user mashes button

---

### Test 6: Re-Render Mid-Install

**During Test 1 (while install is running):**

1. Log pane is showing output, button is disabled
2. Open browser console, run:
   ```javascript
   loadStatus()
   ```
3. Verify:
   - `loadStatus()` completes (doesn't error)
   - Log pane is **not erased**
   - Button still shows "⏳ Installing…"
   - Polling continues uninterrupted

**Why:** The guard at top of `renderStep1()` prevents re-render during install.

**Pass Criteria:**
- `loadStatus()` does NOT clobber the install UI

---

### Test 7: Server Restart Mid-Install

**During Test 1 (while install is ~50% done):**

1. Kill backend process (Ctrl+C in terminal)
2. Frontend shows poll error in log pane:
   ```
   [poll error] Failed to fetch
   ```
3. Button changes to "🔁 Retry Install" (re-enabled)
4. Restart backend:
   ```bash
   cd backend && uvicorn main:app --reload
   ```
5. Click "🔁 Retry Install"
6. Fresh install starts cleanly

**Pass Criteria:**
- Poll error gracefully handled
- User can recover via Retry
- Next install is clean (state reset, no stale logs)

---

## Quick Test Matrix

| Scenario | Duration | Critical Check |
|---|---|---|
| Live Install | 2-5 min | Badges flip ✅, Next unlocks |
| Mock Mode | <1 sec | No button visible |
| Error Simulation | 30 sec | Error surfaces, Retry enabled |
| Polling Stops | During live | Network: zero reqs after success |
| Re-Render Guard | During live | Log not erased by `loadStatus()` |
| Server Restart | During live | User can Retry after restart |

---

## Acceptance Criteria

All tests must **pass** for Phase 3 to be signed off:

- ✅ Live install completes and unlocks Next
- ✅ Mock mode hides install UI
- ✅ Error handling surfaces issue + enables Retry
- ✅ Polling stops cleanly (no leak)
- ✅ Re-render guard prevents log erasure
- ✅ Server restart recovery works

---

## Rollback / Debug

If a test fails:

1. Check backend logs:
   ```bash
   # grep for errors
   tail -50 <uvicorn output>
   ```

2. Check frontend console:
   ```javascript
   // In DevTools console:
   console.log(installPollTimer)  // should be null after success
   // Or during install, should be a timer ID (non-null)
   ```

3. Check state on backend:
   ```python
   # Add breakpoint or print in _run_acs_install():
   print(f"Install state: {_acs_install_state}")
   ```

4. Reset state for retry:
   ```python
   # In Python REPL or add endpoint:
   _acs_install_state["status"] = "idle"
   _acs_install_state["log_lines"] = []
   ```

---

## Notes

- Playwright download is ~100 MB; cache with `pip install --cache-dir` if testing repeatedly
- Log lines may not appear instantly on slow machines; poll interval is forgiving (2s)
- Manual command fallback (`<details>` disclosure) is always available as escape hatch
- No integration test framework needed — manual interaction is the intended test level for this phase
