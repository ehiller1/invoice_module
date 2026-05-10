# ACS Realm Setup Guide

**Audience:** IT staff and treasurers configuring EIME to post journal entries into ACS Realm (the church accounting system from ACS Technologies).

**Goal:** A working, auditable, automated posting pipeline from EIME's HITL queue into ACS Realm's general ledger.

---

## Table of Contents

1. [Obtaining ACS Realm Credentials](#obtaining-acs-realm-credentials)
2. [Understanding ACS Realm Roles](#understanding-acs-realm-roles)
3. [Configuring ACS Credentials in EIME](#configuring-acs-credentials-in-eime)
4. [Testing the ACS Connection](#testing-the-acs-connection)
5. [Troubleshooting ACS Login Failures](#troubleshooting-acs-login-failures)
6. [Understanding Playwright Browser Automation](#understanding-playwright-browser-automation)
7. [First-Time Posting Walkthrough](#first-time-posting-walkthrough-headed-mode)
8. [Handling ACS UI Changes](#handling-acs-ui-changes)
9. [Security Considerations](#security-considerations)
10. [Common ACS Posting Errors](#common-acs-posting-errors-and-solutions)
11. [Sandbox vs Production](#acs-sandbox-vs-production-environments)

---

## Obtaining ACS Realm Credentials

ACS Realm does not publish a public REST API for journal entry posting. EIME therefore drives the ACS web UI through a headless browser. To do this safely you need a **dedicated service account** in ACS Realm — never use a personal user's credentials.

### Step 1: Contact Your Diocesan Administrator

Reach out to whoever administers ACS Realm at your diocese (often the Director of Finance or a diocesan IT contact). Request:

- **A new ACS Realm user named `eime-service`** (or similar identifying name).
- Role: **Bookkeeper** with permissions to **post journal entries** to the relevant General Ledger and Fund modules. Specifically required:
  - `GL.JournalEntry.Create`
  - `GL.JournalEntry.Post`
  - `GL.Account.Read`
  - `Fund.Balance.Read`
- A strong password (24+ characters, generated from a password manager).
- The base URL of your diocese's ACS Realm tenant. It usually looks like `https://realm.acstechnologies.com` or a parish-specific subdomain.

### Step 2: Document the Account

In your password vault, record:

- Username, password, and base URL
- The diocesan contact who provisioned the account
- The activation date and the policy review date (annual)
- A note: "Service account for EIME — do not log in interactively."

### Step 3: First-Time Login (Manually)

Before plugging credentials into EIME, log in once manually with the new account. This is necessary because:

- ACS often requires a **password change on first login**.
- ACS may require **acceptance of terms of service** on first login.
- Some tenants enforce **MFA enrollment** on first login, which would block automation.

If MFA enrollment is required, ask the diocesan admin to **disable MFA for the service account** (or add an exception). EIME's automation cannot solve MFA challenges. Document this exemption in your security-review file.

---

## Understanding ACS Realm Roles

ACS Realm uses a layered permission model. EIME interacts with three modules:

| Module | What EIME Does | Required Permission |
|--------|---------------|---------------------|
| **General Ledger (GL)** | Creates and posts journal entries representing AP invoices, payroll, deposits | `GL.JournalEntry.*` |
| **Funds** | Reads balances of restricted/unrestricted funds before posting | `Fund.Balance.Read` |
| **Transaction Posting** | Submits the JE to the period/posting batch | `GL.Posting.Submit` |

### Recommended Role: "Bookkeeper" with Restrictions

Most dioceses already have a **Bookkeeper** role. Ask the admin to create a **derived role** called `EIME-Service` that includes Bookkeeper but **excludes**:

- Vendor master file edits
- Bank account configuration changes
- User-management actions

This enforces segregation of duties: EIME can post entries but cannot create vendors or change bank routing — those remain human-only.

### Multi-Parish Dioceses

If EIME serves multiple parishes inside one ACS tenant, the service account needs access to each parish's GL. Either:

- Create one service account with multi-parish access (simpler, less granular audit), or
- Create one service account per parish (more granular, more setup work).

The second approach is recommended for dioceses with > 5 parishes.

---

## Configuring ACS Credentials in EIME

### Option A: Via EIME Settings UI

1. Log into EIME as `TREASURER_ADMIN`.
2. Navigate to **Settings → Integrations → ACS Realm**.
3. Enter:
   - Base URL (e.g., `https://realm.acstechnologies.com`)
   - Username (the service account you just created)
   - Password
   - Tenant ID (if your diocese uses tenant-scoped URLs)
4. Click **Save**. EIME encrypts the password with the Fernet key and stores it at `backend/data/acs_credentials.json`.

> **Insert screenshot 1: EIME ACS Realm settings panel.**

### Option B: Via `.env`

```bash
ACS_REALM_BASE_URL=https://realm.acstechnologies.com
ACS_REALM_USERNAME=eime-service@yourdiocese.org
ACS_REALM_PASSWORD=<from password manager>
ACS_HEADLESS=true
ACS_TIMEOUT_MS=60000
```

Restart EIME after editing `.env`.

---

## Testing the ACS Connection

### From EIME UI

1. Go to **Settings → Integrations → ACS Realm → Test Connection**.
2. EIME launches a Playwright browser, navigates to your ACS URL, and attempts login.
3. On success, EIME caches the session cookie and shows a green check.
4. On failure, EIME shows the error message and a screenshot of the failure page (saved to `backend/audit_trails/acs_test_<timestamp>.png`).

### From CLI

```bash
uv run python -m backend.integrations.acs_realm test
```

Expected output:

```
[acs] launching chromium (headless=true)
[acs] navigating to https://realm.acstechnologies.com
[acs] login form found
[acs] submitting credentials
[acs] dashboard loaded — login OK
[acs] session cached for 8 hours
```

### Running in Headed Mode for Debugging

If the test fails, re-run in headed mode to **watch** the browser:

```bash
ACS_HEADLESS=false uv run python -m backend.integrations.acs_realm test
```

A real Chromium window opens. Watch where the script gets stuck — that's almost always either an unexpected popup, a UI change, or an MFA challenge.

---

## Troubleshooting ACS Login Failures

### "Login form not found"

ACS changed their login page DOM. Update selectors (see [Handling ACS UI Changes](#handling-acs-ui-changes)).

### "Invalid credentials"

Either the password was rotated and not updated in EIME, or the account was locked. Log in manually with the same credentials to confirm. If locked, the diocesan admin must unlock.

### "Password change required"

ACS forces password rotation periodically (often every 90 days). EIME cannot change passwords for you. Steps:

1. Log into ACS manually with the service account.
2. Set a new strong password.
3. Update EIME's stored credential (UI or `.env`).
4. Restart EIME.
5. Update the password vault.

Set a calendar reminder 7 days before each rotation date.

### "MFA challenge"

EIME cannot complete MFA. Disable MFA for the service account (see above) or use a hardware-token-style provider that issues long-lived app passwords.

### "Session timeout immediately after login"

Your ACS tenant may use IP-based session binding. If EIME runs from a different IP than your diocesan office, the session is rejected. Ask the admin to whitelist EIME's outbound IP.

---

## Understanding Playwright Browser Automation

### What Playwright Does

[Playwright](https://playwright.dev/) is a Microsoft-maintained library for controlling a real Chromium browser programmatically. EIME uses it to:

1. Open ACS Realm in a Chromium instance.
2. Type the username and password.
3. Click "Sign In".
4. Wait for the dashboard to load.
5. Navigate to **GL → Journal Entry → New**.
6. Fill the JE form (date, accounts, amounts, memo).
7. Click "Post".
8. Capture the resulting JE number and a confirmation screenshot.

### Why Browser Automation?

ACS Realm's only programmatic surface is the web UI — there is no documented REST API for journal entry posting. Playwright is the modern, reliable choice for this kind of automation:

- It uses real Chromium, so it sees what a human user would see (no headless detection issues).
- It auto-waits for elements, reducing flake from slow page loads.
- It captures screenshots and traces, which become part of EIME's audit trail.

### What Could Go Wrong

| Risk | Mitigation |
|------|------------|
| ACS changes a CSS selector | EIME logs a "selector not found" error and aborts; treasurer is notified by email |
| ACS adds a new modal (e.g., "What's new in 2026") | The `dismiss_known_modals` step handles common cases; new ones require selector update |
| Network blip mid-post | EIME retries idempotently using the JE's external reference number; duplicates are detected |
| Posting takes too long | `ACS_TIMEOUT_MS` controls per-step timeout; default 60 seconds |

### Headless vs Headed

- **`ACS_HEADLESS=true` (default, production):** Browser runs invisibly. No GUI required, suitable for servers.
- **`ACS_HEADLESS=false` (debugging only):** A visible browser window appears. **Requires a desktop environment.** Do not use in headless server deployments — Playwright will fail to start without an X server or virtual display.

---

## First-Time Posting Walkthrough (Headed Mode)

The first time you post a real JE through EIME, run in headed mode so you can watch every click. This builds confidence and catches surprises early.

### Prerequisites

- EIME deployed on a workstation with a desktop (your laptop is fine for the first run).
- ACS service account credentials configured.
- One approved invoice ready for posting in the EIME HITL queue.

### Steps

1. Stop the EIME service.
2. Edit `.env` and set `ACS_HEADLESS=false`.
3. Start EIME interactively: `uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000`.
4. In the EIME UI, open the HITL queue and select the approved invoice.
5. Click **Post to ACS**.
6. A Chromium window opens. Watch the script:
   - Navigate to ACS login.
   - Type credentials.
   - Land on the dashboard.
   - Open the Journal Entry form.
   - Fill the date.
   - Add each line item (debit/credit GL, fund, amount, memo).
   - Verify totals balance.
   - Click **Post**.
7. ACS returns a JE number. EIME captures it and writes to `backend/data/journal_entries/<je_id>.json`.
8. EIME also saves a PDF receipt at `backend/audit_pdfs/<je_id>.pdf` and an entry in `audit_trails/audit_log.jsonl`.

> **Insert screenshot 2: Headed Chromium showing ACS JE form mid-fill.**

### After Confirming Success

1. Stop the dev server.
2. Set `ACS_HEADLESS=true` in `.env`.
3. Restart the EIME service normally (`sudo systemctl restart eime`).
4. The next post will run invisibly.

---

## Handling ACS UI Changes

ACS occasionally updates their UI, which can break selectors. EIME isolates all selectors in `backend/integrations/acs_realm/selectors.py` so updates are localized.

### Detecting a Selector Break

Symptoms:

- All postings fail with `TimeoutError: locator 'input[name="username"]' not found`.
- A screenshot in `backend/audit_trails/acs_failure_<timestamp>.png` shows the new UI.

### Updating Selectors

1. Open the failing screenshot to see the new UI.
2. Manually navigate to the same page in a real browser.
3. Open DevTools (F12), inspect the new element, and copy a stable selector. Prefer:
   - `data-testid` attributes if present
   - `aria-label` attributes
   - Stable role + text combinations (`getByRole('button', { name: 'Sign In' })`)
4. Update `backend/integrations/acs_realm/selectors.py`.
5. Run the connection test (`uv run python -m backend.integrations.acs_realm test`).
6. Once green, run a real post in headed mode to confirm.
7. Commit the selector change with a note pointing at the date/screenshot.

### Reporting Selector Drift

If you maintain a fork of EIME, file an issue in your internal tracker including:

- Date observed
- ACS Realm version (visible in the footer)
- The failing selector
- A screenshot

---

## Security Considerations

### Credential Storage

The ACS password is encrypted at rest using the Fernet key (`EIME_FERNET_KEY` in `.env`). On disk, `backend/data/acs_credentials.json` looks like:

```json
{
  "username": "eime-service@yourdiocese.org",
  "password_enc": "gAAAAABh...base64...",
  "base_url": "https://realm.acstechnologies.com",
  "last_rotated": "2026-01-15T10:00:00Z"
}
```

The password is **never** logged in plaintext. If you tail `backend/main.log` and see the password, **stop and file a security incident** — that is a bug.

### Audit Trails

Every ACS interaction creates an audit-log entry:

```json
{
  "ts": "2026-05-07T14:23:01.412Z",
  "actor": "eime-service@yourdiocese.org",
  "action": "acs.je.post",
  "resource": "JE-2026-00134",
  "result": "success",
  "metadata": {
    "invoice_id": "INV-7821",
    "amount_total": 4732.10,
    "lines": 3,
    "browser_session": "sess-abc123",
    "screenshot": "audit_trails/acs_post_je-2026-00134.png"
  },
  "prev_hash": "5f8c2a...",
  "hash": "9e7d4c..."
}
```

The `prev_hash`/`hash` fields form a tamper-evident chain. Any modification to historic entries breaks the chain on the next verification run.

### Network Egress

EIME's outbound calls to ACS use HTTPS only. Configure your firewall to allow outbound 443 to the ACS hostname. If you require SSL inspection, install your CA's root cert into the Chromium trust store; otherwise Playwright will fail TLS validation.

### Service Account Lifecycle

- **Annually:** Rotate the password. Confirm the role still maps to the minimum required permissions.
- **Quarterly:** Review the audit log for unexpected `acs.*` events outside business hours.
- **On treasurer turnover:** Rotate the password (the previous treasurer may know it).
- **On EIME decommission:** Disable the service account in ACS, then revoke. Do not delete — keep for audit.

---

## Common ACS Posting Errors and Solutions

### "Period closed"

You're trying to post a JE dated within a closed accounting period. Open the period in ACS or change the JE date to the current open period. Most parishes close monthly on the 5th business day.

### "Account not found"

The GL account you tried to debit/credit doesn't exist in ACS. Either the COA in EIME is out of sync, or the account was retired. Re-export ACS's chart of accounts and re-import to EIME (`Settings → Chart of Accounts → Import`).

### "Fund out of balance"

ACS enforces fund-level balance: total debits to a fund must equal total credits to that fund within a single JE. EIME normally produces fund-balanced JEs, but if a manual edit broke the balance, the post is rejected. Re-route the JE through HITL for treasurer correction.

### "Duplicate JE reference"

EIME generates a unique external reference per invoice. If you see this error, the previous post likely succeeded but EIME didn't capture the response (network blip). Check ACS for the existing JE and reconcile in EIME via **HITL → Mark as Already Posted**.

### "Browser crashed"

Chromium ran out of memory or hit an OS-level kill. Increase the EIME container/VM RAM to at least 4 GB. Check `dmesg` for OOM kills.

### "Login throttled"

ACS rate-limits failed logins. After 5 failures, the account is locked for 30 minutes. Don't retry — wait, fix credentials, then resume.

---

## ACS Sandbox vs Production Environments

ACS Realm offers a sandbox/training environment for some tenants. If yours has one:

- Sandbox URL: typically `https://sandbox.realm.acstechnologies.com`
- Sandbox data resets monthly — never store real bookkeeping there.
- Use sandbox to:
  - Test EIME upgrades before deploying.
  - Train new treasurers on the workflow.
  - Validate selector updates after ACS UI changes.

To switch EIME between sandbox and production, simply change `ACS_REALM_BASE_URL` and the credentials. Each environment has its own service account.

**Never post real JEs from a production EIME into a sandbox ACS.** They will be lost on the next reset.

---

## Cross-References

- Encryption fundamentals: `SECURITY_BEST_PRACTICES.md`
- Day-2 monitoring of posting success rate: `OPERATIONS_MANUAL.md`
- API endpoints related to ACS: `API_REFERENCE.md`
- Initial setup that includes ACS configuration: `INITIAL_SETUP.md`
- Posting failure debugging: `TROUBLESHOOTING_GUIDE.md`
