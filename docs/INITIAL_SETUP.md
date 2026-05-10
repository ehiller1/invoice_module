# Initial Setup Guide

**Audience:** Finance directors and treasurers configuring EIME for the first time.

**Goal:** A complete, working EIME instance for your church or parish — ready to ingest invoices, route approvals, verify funds, and post journal entries — by end of day one.

---

## Table of Contents

1. [Before You Begin](#before-you-begin)
2. [Step 1: Create Your Church Profile](#step-1-create-your-church-profile)
3. [Step 2: Upload Your Chart of Accounts](#step-2-upload-your-chart-of-accounts-coa)
4. [Step 3: Set Up Approval Chains](#step-3-set-up-approval-chains)
5. [Step 4: Set Up Budgetary Authority Matrix](#step-4-set-up-budgetary-authority-matrix)
6. [Step 5: Import Your Annual Budget](#step-5-import-your-annual-budget)
7. [Step 6: Link Bank Accounts with Plaid](#step-6-link-bank-accounts-with-plaid)
8. [Step 7: Configure ACS Realm Credentials](#step-7-configure-acs-realm-credentials)
9. [Step 8: Create User Accounts and Roles](#step-8-create-user-accounts-and-roles)
10. [Step 9: Test with a Sample Invoice](#step-9-test-with-a-sample-invoice)
11. [Step 10: Understand the Approval Workflow](#step-10-understand-the-approval-workflow)
12. [Step 11: First Real Payment Approval Walkthrough](#step-11-first-real-payment-approval-walkthrough)
13. [Where to Go Next](#where-to-go-next)

---

## Before You Begin

You'll move faster if you collect this information before opening EIME:

- [ ] Your church's denomination (Episcopal, Catholic, Methodist, etc.)
- [ ] Your fiscal year start date (often January 1 or July 1)
- [ ] An export of your **current chart of accounts** from ACS Realm (CSV or Excel)
- [ ] Your **annual budget** spreadsheet for the current fiscal year
- [ ] **Plaid Client ID and Secret** (see `PLAID_SETUP.md`)
- [ ] **ACS Realm service account credentials** (see `ACS_REALM_SETUP.md`)
- [ ] A list of **approvers** by role (rector, vestry treasurer, finance committee chair) with email addresses
- [ ] **SMTP credentials** for sending approval emails (your existing email-sender service or SendGrid)

Allow about **3 hours** of focused time. You can pause and resume — EIME persists each step.

---

## Step 1: Create Your Church Profile

The church profile drives downstream behavior: fund restrictions, denominational rules, and reporting templates.

1. Open EIME at `https://eime.yourchurch.org` (or `http://localhost:8000` in development).
2. On first launch, you'll see the **Welcome Wizard**. If it's been dismissed, navigate to **Settings → Church Profile**.
3. Fill in:

| Field | Example | Notes |
|-------|---------|-------|
| Legal Name | "St. Mark's Episcopal Church" | Appears on all reports |
| Common Name | "St. Mark's" | Used in UI |
| Denomination | Episcopal | Drives fund-restriction defaults |
| Diocese | Diocese of Atlanta | Optional |
| EIN | 58-1234567 | For audit reports |
| Fiscal Year Start | January 1 | Used for YTD calculations |
| Reporting Standard | FASB ASC 958 | Default for U.S. churches |
| Currency | USD | Multi-currency not supported |
| Address | 123 Main St, Anytown, GA 30303 | For PDF receipts |

4. Click **Save**.

> **Insert screenshot 1: Church Profile form.**

---

## Step 2: Upload Your Chart of Accounts (COA)

The COA tells EIME which GL accounts exist, their natural balance (debit/credit), and which fund they belong to. EIME's GL classifier uses this list as the universe of valid targets.

### Export from ACS

1. In ACS Realm, navigate to **Reports → General Ledger → Chart of Accounts**.
2. Export to **CSV** with columns:
   - GL Code (e.g., `5100-001-000`)
   - Account Name (e.g., `Office Supplies — General Fund`)
   - Type (Asset / Liability / Equity / Revenue / Expense)
   - Fund (General / Restricted-Music / Endowment / etc.)
   - Active (Y/N)

### Import into EIME

1. Navigate to **Settings → Chart of Accounts → Import**.
2. Click **Choose File** and select the CSV.
3. EIME shows a preview of the first 10 rows. Confirm the column mapping.
4. Click **Import**.
5. EIME validates each row. Errors show in red — typically:
   - Missing GL code
   - Unknown fund name
   - Duplicate code
6. Fix errors in the CSV and re-upload, **or** click **Skip Errors** to proceed with valid rows only.

> **Insert screenshot 2: COA import preview screen.**

### Verify

After import, navigate to **Settings → Chart of Accounts** and confirm the count matches your ACS export. You can also click into any account to see its details.

EIME stores the COA at `backend/data/chart_of_accounts.json`.

---

## Step 3: Set Up Approval Chains

An **approval chain** maps a GL pattern to a person who must approve invoices coded to that GL. Patterns use prefixes — for example, `5100-*` covers all office-supply accounts.

### Understanding Patterns

| Pattern | Matches | Typical Approver |
|---------|---------|------------------|
| `*` | Everything (fallback) | Treasurer |
| `5100-*` | Office supplies | Office Manager |
| `5500-*` | Music & worship | Music Director |
| `5800-*` | Building & grounds | Property Committee Chair |
| `6000-*` | Salaries | Rector |
| `2100-001-*` | Restricted Music Fund | Music Director + Treasurer (dual) |

### Configure

1. Navigate to **Settings → Approvals → Approval Chains**.
2. Click **Add Chain**.
3. Enter:
   - **GL Pattern** (e.g., `5500-*`)
   - **Approver Email** (e.g., `music-director@yourchurch.org`)
   - **Threshold** (e.g., `$0` to require approval on all amounts, or `$500` to auto-approve below that)
   - **Backup Approver** (optional, used if primary doesn't respond in 48 hours)
4. Click **Save**.
5. Repeat for each GL grouping.

Always end with a fallback chain `*` → Treasurer to catch invoices that don't match any specific pattern.

> **Insert screenshot 3: Approval Chains configuration.**

EIME stores chains at `backend/data/approval_chains.json`.

---

## Step 4: Set Up Budgetary Authority Matrix

The authority matrix limits **how much** any role can approve. It encodes your bylaws or vestry policy in machine-readable form.

### Example Matrix

| Role | GL Pattern | Max Single Approval | Max Monthly Cumulative |
|------|------------|---------------------|------------------------|
| BUDGET_OWNER | (their assigned GL) | $1,000 | $5,000 |
| TREASURER_ADMIN | `*` | $25,000 | $100,000 |
| RECTOR | `*` | $50,000 | unlimited |
| VESTRY (dual signature) | `*` over $50,000 | unlimited | unlimited |

### Configure

1. Navigate to **Settings → Approvals → Authority Matrix**.
2. Click **Add Rule**.
3. Enter:
   - **Role** (must match a role you'll assign in Step 8)
   - **GL Pattern** (or `*` for all)
   - **Max Single** (in dollars)
   - **Max Monthly** (cumulative cap)
   - **Requires Dual Signature** (yes/no — triggers second approver above the threshold)
4. Click **Save**.

EIME stores the matrix at `backend/data/budgetary_authority.json`.

> **Insert screenshot 4: Authority Matrix.**

---

## Step 5: Import Your Annual Budget

Budget data lets EIME flag overruns at approval time and produce variance reports.

### Spreadsheet Format

EIME accepts an Excel file with one row per GL/month combination:

| gl_code | fund | jan | feb | mar | apr | may | jun | jul | aug | sep | oct | nov | dec |
|---------|------|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|
| 5100-001-000 | General | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| 5500-100-000 | Music | 500 | 500 | 1000 | 500 | 500 | 500 | 500 | 500 | 1500 | 500 | 500 | 2000 |

A template is available at **Settings → Budget → Download Template**.

### Import

1. Navigate to **Settings → Budget → Import**.
2. Choose your Excel file.
3. Confirm the fiscal year (defaults to current).
4. Click **Import**.
5. EIME shows a summary: total budget, count of GLs covered, count of unmatched GLs.
6. Resolve unmatched GLs (typically a code mismatch with the COA) and re-import.

EIME stores the budget at `backend/data/budget.json`.

> **Insert screenshot 5: Budget import summary.**

---

## Step 6: Link Bank Accounts with Plaid

Detailed walkthrough is in `PLAID_SETUP.md`. The short version:

1. Configure Plaid Client ID and Secret under **Settings → Integrations → Plaid**.
2. Navigate to **Banking → Linked Accounts → Add Account**.
3. The Plaid Link modal opens. Search for your bank, log in, choose accounts to share.
4. EIME stores an encrypted access token and shows current balances.

Link **all** accounts EIME should see — at minimum the operating account. Ideally also payroll, money market, and any restricted endowment accounts so EIME can verify fund-balance compliance.

---

## Step 7: Configure ACS Realm Credentials

Detailed walkthrough is in `ACS_REALM_SETUP.md`. Short version:

1. Get a **dedicated service account** in ACS Realm from your diocesan admin.
2. In EIME, go to **Settings → Integrations → ACS Realm**.
3. Enter base URL, username, password.
4. Click **Test Connection**. A green check confirms login works.

Do this **before** any real invoices flow through, so the first JE post does not surprise you with an authentication error.

---

## Step 8: Create User Accounts and Roles

EIME ships three roles. Detailed responsibilities are in `ROLES_AND_PERMISSIONS.md`.

| Role | Who Gets It | What They Can Do |
|------|-------------|------------------|
| **FINANCE_STAFF** | Bookkeeper, AP clerk, finance committee members | View reports, view HITL queue (read-only) |
| **BUDGET_OWNER** | Department heads (music, education, property) | Approve invoices coded to their GL up to their amount cap |
| **TREASURER_ADMIN** | Treasurer, finance director | Configure system, override blocks, post JEs, manage users |

### Create Each User

1. Navigate to **Settings → Users → Add User**.
2. Enter:
   - Full name
   - Email
   - Role (one of the three above)
   - Assigned GL patterns (for `BUDGET_OWNER` only)
   - Single-approval max (for `BUDGET_OWNER` only; defaults from Step 4 matrix)
3. Click **Save**.
4. EIME emails the user a setup link to choose their password.

> **Insert screenshot 6: User management screen.**

### First Treasurer-Admin

The very first `TREASURER_ADMIN` is created during initial deployment via:

```bash
uv run python -m backend.tools.create_admin --email treasurer@yourchurch.org
```

You used that account to do everything in this guide. Add at least one **backup** TREASURER_ADMIN now so you're not the single point of failure.

---

## Step 9: Test with a Sample Invoice

EIME ships sample invoices in `samples/`. Use one for end-to-end testing.

### Walkthrough

1. Navigate to **Invoices → Upload**.
2. Drag-and-drop `samples/sample_invoice_office_supplies.pdf`.
3. EIME's **Ingestion Agent** extracts vendor, date, line items, and total. This takes 5–15 seconds.
4. The **Classification Agent** proposes a GL code with a confidence score.
5. The **Risk Agent** evaluates fraud signals (duplicate invoice number, unusual vendor, spike vs historical average).
6. The **Budget Agent** checks YTD spend vs the budget you imported in Step 5.
7. If everything is clean and confidence is high, the invoice routes to the appropriate approver per Step 3 chains.
8. If anything is off, the invoice escalates to **HITL** (human-in-the-loop) for treasurer review.

### What You Should See

- A new card in the **Invoices** dashboard.
- Status: `Pending Approval` or `Pending HITL`.
- An audit-trail entry at `backend/audit_trails/audit_log.jsonl`.

If this works, EIME is wired up correctly end-to-end.

> **Insert screenshot 7: Invoice dashboard with sample invoice processed.**

---

## Step 10: Understand the Approval Workflow

The full lifecycle of an invoice in EIME:

```
   PDF UPLOAD
       │
       ▼
  ┌──────────────┐
  │ INGESTION    │ Extract vendor, date, lines, total
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ CLASSIFY GL  │ Semantic search → GL + confidence
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ RISK + BUDGET│ Fraud / variance / fund restriction
  └──────┬───────┘
         ▼
   confidence ≥ 0.85 AND no risks?
         │
    ┌────┴────┐
    ▼         ▼
   YES       NO ──> HITL QUEUE (treasurer review)
    │
    ▼
  ┌──────────────┐
  │ ROUTE EMAIL  │ Per Step 3 chain
  └──────┬───────┘
         ▼
  approver clicks Approve / Reject
         │
    ┌────┴────┐
    ▼         ▼
   APPROVE   REJECT ──> archived with reason
    │
    ▼
  ┌──────────────┐
  │ FUND CHECK   │ Plaid balance ≥ amount?
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ POST TO ACS  │ JE created in ACS Realm
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ PAYMENT FILE │ ACH / check / bill-pay
  └──────────────┘
```

Each transition is logged to the audit trail with the actor, timestamp, and decision rationale.

---

## Step 11: First Real Payment Approval Walkthrough

Once the sample test passes, run a real invoice end-to-end as your first live transaction. Pick a small, low-risk one — for example, a routine office-supplies invoice under $200.

1. **Upload** the invoice via the EIME UI.
2. **Watch ingestion** — confirm the extracted vendor, date, and amount match the PDF.
3. **Confirm GL classification** — if confidence is below 0.85, manually pick the right GL and EIME will learn from the correction.
4. **Approval email** — the responsible budget owner gets an email with **Approve** and **Reject** buttons. Click **Approve** as that user.
5. **Fund check** — EIME calls Plaid for current balance. Should succeed instantly.
6. **Post to ACS** — first time, run in **headed mode** (see `ACS_REALM_SETUP.md`) so you can watch.
7. **Verify in ACS** — log into ACS Realm manually and confirm the JE is there with the correct accounts and amount.
8. **Pay the vendor** — through your normal AP rail (ACH file, check, online bill pay). EIME does not move money.
9. **Mark Paid** — return to EIME, find the invoice, click **Mark as Paid**, enter the payment reference (check #, ACH trace).
10. **Reconciliation** — at month-end, EIME matches the cleared transaction from Plaid against this JE automatically.

> **Insert screenshot 8: End-to-end invoice trail.**

After this first successful run, congratulations — you're operational.

---

## Where to Go Next

| Topic | Document |
|-------|----------|
| Daily/weekly/monthly tasks | `OPERATIONS_MANUAL.md` |
| Who can do what | `ROLES_AND_PERMISSIONS.md` |
| Common questions from staff | `FAQ.md` |
| When something breaks | `TROUBLESHOOTING_GUIDE.md` |
| Securing the deployment | `SECURITY_BEST_PRACTICES.md` |
| Connecting external tools | `API_REFERENCE.md` |

You should now have:

- A configured church profile
- An imported COA and budget
- Approval chains and authority matrix in place
- Plaid linked and balances visible
- ACS Realm wired up and tested
- At least 2 admin users + initial budget owners
- A successful sample invoice run
- A successful real-invoice run end-to-end

Schedule a 30-day review with your finance committee to validate the workflow against your bylaws and audit requirements.
