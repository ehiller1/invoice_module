# Plaid Setup Guide

**Audience:** Treasurers and finance staff connecting EIME to bank accounts via Plaid.

**Goal:** A working Plaid integration so EIME can read live bank balances, verify funds before payment release, and pull transactions for reconciliation.

---

## Table of Contents

1. [What is Plaid and Why Use It](#what-is-plaid-and-why-use-it)
2. [Getting a Plaid Sandbox Account](#getting-a-plaid-sandbox-account)
3. [Obtaining Client ID and Secret](#obtaining-client-id-and-secret)
4. [Configuring Credentials in EIME](#configuring-credentials-in-eime)
5. [Testing the Plaid Connection](#testing-the-plaid-connection)
6. [Linking Bank Accounts](#linking-bank-accounts)
7. [Understanding Account Types](#understanding-account-types)
8. [Balance Refresh Frequency](#balance-refresh-frequency)
9. [Security Best Practices](#security-best-practices)
10. [Troubleshooting](#troubleshooting)
11. [Plaid Pricing and Cost Considerations](#plaid-pricing-and-cost-considerations)
12. [Upgrading from Sandbox to Production](#upgrading-from-sandbox-to-production)

---

## What is Plaid and Why Use It

Plaid is a financial data aggregator that lets EIME connect to over 12,000 U.S. banks and credit unions through a single, standardized API. EIME uses Plaid for three things:

1. **Balance verification** — Before releasing a payment, EIME confirms the operating account has sufficient funds.
2. **Transaction download** — For monthly bank reconciliation, EIME pulls cleared transactions and matches them to journal entries.
3. **Multi-account awareness** — Many parishes hold multiple accounts (operating, payroll, restricted endowment). Plaid lets EIME see all of them in one place.

**Why not screen-scraping or manual statements?** Screen-scraping breaks when banks update their UI, and manual statements introduce a 30-day lag and a typo risk. Plaid is bank-blessed, encrypted in transit, and refreshes daily.

**What Plaid does NOT do in EIME:** Plaid is read-only. EIME does not move money through Plaid. Outgoing payments are still sent via your existing AP rails (ACH file, check run, online bill pay).

---

## Getting a Plaid Sandbox Account

Plaid offers a free sandbox tier for development and small-volume production use. Most parishes can run on the free tier indefinitely.

### Step 1: Sign Up

1. Open a browser and go to <https://dashboard.plaid.com/signup>.
2. Enter your work email (use a role-based address like `treasurer@yourchurch.org`, not a personal address).
3. Choose a strong password and enable two-factor authentication immediately under **Account Settings → Security**.
4. Verify your email.

> **Insert screenshot 1: Plaid signup form.**

### Step 2: Complete Organization Profile

Plaid asks a few questions about your organization. Use:

- **Company name:** Your legal church name (e.g., "St. Mark's Episcopal Church")
- **Use case:** "Personal finance management" or "Bookkeeping"
- **Geography:** United States
- **Expected volume:** "1–100 API calls per day" for most parishes

### Step 3: Confirm You're in the Sandbox

After signup, the dashboard defaults to **Sandbox** mode (visible in the top-left environment selector). You'll see a banner: *"You're in Sandbox. Use test credentials user_good / pass_good to link a fake bank."*

> **Insert screenshot 2: Plaid dashboard in Sandbox mode.**

---

## Obtaining Client ID and Secret

EIME authenticates to Plaid with two strings: **Client ID** (public, identifies your app) and **Secret** (private, proves it's you).

### Step 1: Open the Keys Page

1. In the Plaid dashboard, click **Team Settings** in the left sidebar.
2. Click **Keys**.

### Step 2: Copy the Sandbox Credentials

You will see three columns: **Sandbox**, **Development**, **Production**. Each has its own Client ID (same across rows) and a separate Secret per environment.

- **Client ID:** Copy the value labeled `client_id`. It looks like `5f8c2a1b9e7d4c0012345678`.
- **Sandbox Secret:** Click **Reveal** next to the Sandbox row, then **Copy**. It looks like `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5`.

> **Insert screenshot 3: Plaid Keys page with Sandbox Reveal button highlighted.**

### Step 3: Store the Secret Securely

The Secret is shown only when revealed. Treat it like a password:

- Paste it into your password manager (1Password, Bitwarden, or your diocese's vault).
- **Do not** paste it into chat, email, or a sticky note.
- **Do not** commit it to git. EIME's `.env` file is gitignored for this reason.

If a Secret is ever exposed, click **Rotate** in the Plaid dashboard immediately. The old secret stops working within 60 seconds.

---

## Configuring Credentials in EIME

You can configure Plaid credentials two ways: via the EIME settings UI (recommended) or directly in `.env`.

### Option A: Via EIME Settings UI

1. Log into EIME as `TREASURER_ADMIN`.
2. Navigate to **Settings → Integrations → Plaid**.
3. Paste your **Client ID** and **Secret**.
4. Choose environment: `sandbox`, `development`, or `production`.
5. Click **Save**. EIME encrypts the secret with the Fernet key from `.env` and stores it in `backend/data/plaid_items.json`.

> **Insert screenshot 4: EIME Plaid settings panel.**

### Option B: Via `.env` File

Edit `/opt/eime/.env`:

```bash
PLAID_CLIENT_ID=5f8c2a1b9e7d4c0012345678
PLAID_SECRET=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5
PLAID_ENV=sandbox
PLAID_PRODUCTS=auth,transactions
PLAID_COUNTRY_CODES=US
```

Then restart the EIME service:

```bash
sudo systemctl restart eime
```

`.env` values take precedence over UI-stored values when both exist.

---

## Testing the Plaid Connection

### Quick Test from EIME

1. In EIME, go to **Settings → Integrations → Plaid → Test Connection**.
2. EIME calls Plaid's `/link/token/create` endpoint.
3. A green checkmark and "Plaid reachable" message confirm success.

### Quick Test from CLI

```bash
curl -s -X POST https://sandbox.plaid.com/institutions/get \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$PLAID_CLIENT_ID\",\"secret\":\"$PLAID_SECRET\",\"count\":1,\"offset\":0,\"country_codes\":[\"US\"]}"
```

A successful response includes a `request_id` and a list of one institution. An `INVALID_API_KEYS` error means your Client ID or Secret is wrong, or you mixed sandbox and production values.

---

## Linking Bank Accounts

EIME embeds the **Plaid Link** modal — Plaid's official, bank-branded login dialog. Your bank credentials never touch EIME servers; they go directly from your browser to Plaid.

### Walkthrough

1. In EIME, navigate to **Banking → Linked Accounts → Add Account**.
2. The Plaid Link modal opens. Click **Continue**.
3. Search for your bank (e.g., "Chase", "Wells Fargo", "Local Credit Union").
4. **In sandbox**, type any bank name, then use:
   - Username: `user_good`
   - Password: `pass_good`
   - 2FA code (if prompted): `1234`
5. **In production**, enter your real online banking username and password. If your bank uses 2FA, complete the SMS or app challenge.
6. Plaid asks which accounts to share. **Check only the accounts EIME should see** — typically operating, payroll, and any restricted funds.
7. Click **Continue**. Plaid returns a `public_token` to EIME.
8. EIME exchanges it for a long-lived `access_token` and encrypts it at rest.

> **Insert screenshot 5: Plaid Link modal account selection.**

### After Linking

EIME displays the linked accounts under **Banking → Linked Accounts**:

| Account Name | Type | Mask | Current Balance | Last Refresh |
|--------------|------|------|-----------------|--------------|
| Operating Checking | depository/checking | ...4521 | $48,732.10 | 2 minutes ago |
| Payroll Reserve | depository/savings | ...8902 | $12,000.00 | 2 minutes ago |
| Endowment Money Market | depository/money market | ...3344 | $245,000.00 | 2 minutes ago |

---

## Understanding Account Types

Plaid classifies every account with a `type` and `subtype`. EIME uses these for restriction logic.

| Plaid Type/Subtype | EIME Usage |
|--------------------|------------|
| `depository / checking` | Operating account; default source for AP payments |
| `depository / savings` | Reserve / payroll buffer |
| `depository / money market` | Often restricted endowment funds — flagged for scrutiny |
| `depository / cd` | Locked funds — EIME excludes from operating-cash totals |
| `credit / credit card` | Tracked for reconciliation only; never used as payment source |
| `loan / *` | Read-only for monitoring; not used for AP |

When you link a money market or endowment account, EIME automatically tags it as a **restricted** source. Payments drawing on restricted funds require an explicit `TREASURER_ADMIN` override and a documented purpose code.

---

## Balance Refresh Frequency

Plaid balances refresh on three triggers:

1. **On-demand** — When EIME's payment release flow runs, it calls `/accounts/balance/get` synchronously. This adds ~500 ms to the release flow but guarantees a real-time number.
2. **Scheduled** — `backend/scheduler.py` polls every 4 hours during business hours (configurable).
3. **Webhook** — When you upgrade to Plaid Production, you can register a webhook URL. Plaid pushes `DEFAULT_UPDATE` events when transactions clear.

**Sandbox limitation:** Plaid sandbox does not push webhooks reliably. Use scheduled polling for sandbox testing.

---

## Security Best Practices

### Access Token Encryption

The Plaid `access_token` is the long-lived credential — anyone who steals it can read your bank balances forever (or until you rotate). EIME encrypts it with Fernet (AES-128-CBC + HMAC) using the `EIME_FERNET_KEY` from `.env`. The encrypted blob lives at `backend/data/plaid_items.json`.

**If your Fernet key is ever exposed:**

1. Rotate the key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
2. Re-encrypt all stored items with the new key (EIME provides `uv run python -m backend.tools.rotate_fernet`).
3. Audit the `audit_trails/audit_log.jsonl` for any unauthorized `plaid.balance.read` events.

### Credential Rotation

Plaid Secrets should rotate annually:

1. In Plaid dashboard, **Team Settings → Keys → Rotate** for the relevant environment.
2. The dashboard generates a new secret. **Both old and new work for 60 seconds.**
3. Update EIME's `.env` (or UI setting) with the new secret.
4. Restart EIME.
5. Confirm Plaid dashboard shows the old secret as "expired".

### Least-Privilege Linking

When linking accounts in Plaid Link, **only share accounts EIME needs**. Personal accounts at the same bank should never appear in the EIME selection — uncheck them.

### Audit Trail

Every Plaid API call EIME makes is logged to `audit_trails/audit_log.jsonl` with:

- Timestamp
- User who triggered the call (or `system` for scheduled refreshes)
- Endpoint called (`/accounts/balance/get`, etc.)
- Account masks involved (never full numbers)
- Result code

Review this log monthly (see `OPERATIONS_MANUAL.md`).

---

## Troubleshooting

### `INVALID_API_KEYS`

Your Client ID or Secret is wrong, **or** you used a sandbox secret against the production endpoint (or vice versa). Double-check `PLAID_ENV` matches the secret you copied.

### `INVALID_ACCESS_TOKEN`

The user revoked EIME's access from the bank's online portal, or you restored from a stale backup. Re-link the account from **Banking → Linked Accounts → Re-authenticate**.

### `ITEM_LOGIN_REQUIRED`

The bank requires periodic re-authentication (often every 90–180 days). EIME shows a yellow banner. Click **Re-authenticate** and complete the Plaid Link flow again. Your historical transactions remain intact.

### `RATE_LIMIT_EXCEEDED`

You exceeded the free-tier API quota (200 calls/day in sandbox, varies in production). Spread out balance refreshes or upgrade your Plaid plan. Reduce `BALANCE_REFRESH_INTERVAL` in `.env`.

### Plaid Link modal doesn't open

Browser ad-blocker or popup-blocker is interfering. Allow popups for your EIME domain. Plaid's CDN must be reachable (`cdn.plaid.com`).

### Balance shows "Unavailable"

Some banks return `available_balance: null` for money market accounts. Use `current_balance` instead — EIME falls back automatically but flags the account in the dashboard.

---

## Plaid Pricing and Cost Considerations

Plaid pricing changes; check <https://plaid.com/pricing/> for current numbers. As of mid-2025:

| Plan | Monthly Cost | Best For |
|------|--------------|----------|
| **Free Sandbox** | $0 | Development, training, single-test-account |
| **Pay-as-you-go (Production)** | ~$0.30/account/month + per-call fees | Most single-parish deployments |
| **Custom Enterprise** | Negotiated | Multi-site dioceses, > 50 linked accounts |

**Typical parish cost:** 3–5 linked accounts × $0.30 + ~$5/month in API calls = **~$7–10/month**.

Multi-parish dioceses should contact Plaid sales for a per-parish discount.

---

## Upgrading from Sandbox to Production

Sandbox is fine for training and pilot, but for live operations you need Plaid **Production** access.

### Step 1: Request Production Access

1. In the Plaid dashboard, switch the environment dropdown to **Production**.
2. You'll be prompted to fill out a **Production Application** with:
   - Your church's legal name and EIN
   - A privacy policy URL
   - A description of how you use Plaid data ("read-only balance and transaction data for internal bookkeeping and reconciliation")
   - Expected volume
3. Plaid reviews applications in 1–3 business days.

### Step 2: Get Production Credentials

Once approved, the **Keys** page shows a Production Secret. Reveal and copy it.

### Step 3: Update EIME

Update `.env`:

```bash
PLAID_ENV=production
PLAID_SECRET=<production secret>
```

The Client ID is the same across all environments. Restart EIME.

### Step 4: Re-Link All Accounts

**Sandbox access tokens are not valid in production.** Every linked account must be re-linked through Plaid Link in production mode. Walk through each one with the treasurer.

### Step 5: Register a Webhook (Optional but Recommended)

In Plaid dashboard, set the webhook URL to `https://eime.yourchurch.org/api/plaid/webhook`. EIME validates the webhook signature before processing — see `API_REFERENCE.md` for the verification rule.

---

## Cross-References

- Encryption details: `SECURITY_BEST_PRACTICES.md`
- Daily Plaid health monitoring: `OPERATIONS_MANUAL.md`
- Plaid API endpoints exposed by EIME: `API_REFERENCE.md`
- Initial setup that includes Plaid linking: `INITIAL_SETUP.md`
