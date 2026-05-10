# EIME Frequently Asked Questions

**Audience:** Anyone — finance staff, IT, vestry members, auditors.

**Goal:** Quick answers to the questions that come up most often.

---

## Table of Contents

1. [Account & Login](#account--login)
2. [Invoices & Approvals](#invoices--approvals)
3. [Bank Connections (Plaid)](#bank-connections-plaid)
4. [General Ledger & ACS Realm](#general-ledger--acs-realm)
5. [Reports & Reconciliation](#reports--reconciliation)
6. [Audit & Compliance](#audit--compliance)
7. [Operational Limits](#operational-limits)

---

## Account & Login

### How do I reset my password?

In the current build, there is no self-service password reset — this is intentional, to avoid email-based account takeover risks. Instead, ask any `TREASURER_ADMIN` to issue a **password-reset link** from **Settings → Users → Edit → Send Reset Link**. The link is valid for 24 hours.

A self-service flow with email + secondary verification is on the roadmap.

### I'm a TREASURER_ADMIN and I'm locked out — now what?

If at least one other `TREASURER_ADMIN` exists, ask them to reset you. If there are no other admins, the IT team must run:

```bash
uv run python -m backend.tools.create_admin --email your-email@example.org
```

This is why we strongly recommend at least 2 active `TREASURER_ADMIN` users at all times.

### Why did I get logged out?

Sessions expire after 24 hours of inactivity (8 hours for `TREASURER_ADMIN`). Also, any password change immediately invalidates all sessions for that user. Just log back in.

### Can I share my account with my assistant?

No. EIME's audit trail attributes every action to the logged-in user, and segregation-of-duties controls depend on that being accurate. Create a separate account for your assistant — usually `FINANCE_STAFF` is enough for assistant tasks.

---

## Invoices & Approvals

### Why did this invoice escalate to HITL?

EIME escalates to HITL (human-in-the-loop) when any of these is true:

- **Low GL classification confidence** (< 0.85) — the agent isn't sure which account this should hit.
- **Risk score ≥ 0.7** — duplicate invoice number, unusual vendor, amount spike, etc.
- **Budget overrun** — approving this would push YTD over the budget cap.
- **Fund restriction violation** — the proposed source fund can't legally pay this expense.
- **Approval chain unmatched** — no chain rule covers this GL pattern.
- **Approver missed deadline** — primary and backup both didn't act in 5 business days.

Open the invoice in HITL and read the **Reasoning** panel for the specific signal that triggered escalation.

### Can I override a payment block?

Depends on the block:

| Block Type | Who Can Override |
|------------|------------------|
| Low classification confidence | `TREASURER_ADMIN` (by manually picking the GL) |
| Budget overrun | `TREASURER_ADMIN` (with memo justifying overrun) |
| Insufficient bank balance | `TREASURER_ADMIN` (with memo; e.g., "deposit clearing tomorrow") |
| Fund restriction violation | `TREASURER_ADMIN` (with memo; logged for audit review) |
| Denomination-specific bylaw | **Cannot be overridden** — must reroute or reject |

Every override is logged with the actor and the memo, and these entries are highlighted in the monthly audit-trail review.

### How do I add a new GL code?

Two options:

1. **Add to ACS first**, then **Settings → Chart of Accounts → Re-import** in EIME. This keeps both systems in sync.
2. Or in EIME, **Settings → Chart of Accounts → Add**. EIME will warn you that the code is not in ACS — you'll need to add it there before any JE using it can post.

Always option 1 in production.

### Can I bulk upload invoices?

Currently **only via the UI** (drag-and-drop multiple files at once, processed sequentially). A batch API endpoint is planned for a future release. For now, drag up to 20 PDFs at a time.

### Why did my invoice take 30 seconds to process?

First invoice after a service restart triggers ML model loading (cold start). Subsequent invoices process in 5–15 seconds. Set `EIME_PREWARM=true` in `.env` to warm models on boot.

### What if EIME classifies an invoice to the wrong GL?

In HITL, click **Reclassify**. EIME stores the correction. After 5+ corrections for the same vendor or pattern, the agent learns the right mapping for next time.

For invoices already posted to ACS, EIME pushes a **correcting JE** rather than editing — that preserves the audit trail.

### Why did the approval email go to the backup, not the primary?

Two possibilities:

1. **The primary didn't act within 48 hours.** EIME automatically escalates to backup on the third day.
2. **The primary's email is bouncing.** Check **Reports → System → SMTP Bounces** and update the address.

---

## Bank Connections (Plaid)

### How often are bank balances updated?

Three triggers:

1. **On-demand** before any payment release (synchronous; ~500 ms).
2. **Scheduled** every 4 hours during business hours.
3. **Webhook** when transactions clear (production Plaid only).

You can also force an update via **Banking → Refresh All**.

### What happens if the Plaid connection drops?

EIME shows a yellow or red badge on the affected account. You have three options:

- **Re-authenticate** through Plaid Link if the bank just needs a re-login.
- **Manual statement upload** — drag a CSV or PDF statement to **Reconciliation → Manual Statement** as a fallback. EIME parses and reconciles as if it came from Plaid.
- **Wait** — many disconnections are transient (bank maintenance windows).

Your books don't stop because Plaid does. Manual fallback exists exactly for this.

### Will my bank charge me for Plaid access?

No — Plaid is read-only and uses standard online-banking credentials. Your bank does not charge you. Plaid charges EIME a per-account-per-month fee (around $0.30 for most banks); see `PLAID_SETUP.md` for current pricing.

### Can EIME move money through Plaid?

No, by design. Plaid is read-only in EIME. Outgoing payments use your existing AP rails (ACH file, check run, online bill pay). This keeps the **payment authorization** step firmly in human hands.

---

## General Ledger & ACS Realm

### Why does EIME post JEs to ACS via a browser instead of an API?

ACS Realm doesn't publish a public REST API for journal entry posting. Browser automation (via Playwright) is the supported integration path. See `ACS_REALM_SETUP.md` for details.

### What if ACS changes their UI?

EIME will fail to post and write a screenshot of the new UI to `backend/audit_trails/`. The IT team updates selectors in `backend/integrations/acs_realm/selectors.py` (procedure in `ACS_REALM_SETUP.md`). Posts resume after the selector fix.

### Can I see the JE in ACS before EIME posts?

Yes — the first time you post, run in **headed mode** (`ACS_HEADLESS=false`). A real browser window shows you every step. After confirming the workflow, switch back to headless for production.

### What happens if a post fails halfway through?

EIME captures the failure point, records it to the audit trail, and **does not retry automatically**. The treasurer reviews the failure and clicks **Retry** in HITL after fixing the underlying cause (e.g., updated selector, rotated password). EIME uses idempotent external references, so retries don't create duplicates.

---

## Reports & Reconciliation

### Why doesn't my Budget vs Actual report match my spreadsheet?

Common causes:

- **COA mismatch** — your imported budget references GL codes that drifted in EIME's COA. Re-export from ACS and re-import.
- **Fund tag missing** — a JE was posted without a fund, so it didn't roll up to the right fund's variance.
- **Period boundary** — a March 31 invoice posted with an April 1 date will show in April, not March.
- **Budget amendment not applied** — confirm you imported the latest amendment.

See `TROUBLESHOOTING_GUIDE.md` → Budget Comparison Shows Wrong Numbers.

### Can EIME do my full month-end close?

EIME automates the heavy lifting: JE posting, fund balancing, bank reconciliation, variance reports. The treasurer still:

- Reviews and approves edge cases.
- Investigates variances and codes corrections.
- Posts manual adjusting JEs (depreciation, accruals).
- Signs off on the reconciliation.

A typical 3-day close becomes a half-day close.

### Why are some bank lines unmatched after running reconciliation?

Reasons:

- **Timing** — JE in EIME, but bank hasn't cleared yet (normal for ACH float; auto-matches when it clears).
- **Vendor name mismatch** — bank shows "POS PURCHASE 04/15", EIME has the friendly vendor name. Add a vendor alias.
- **Bank-only items** — fees, interest, returned-item charges that aren't in EIME yet. Add a manual JE.
- **EIME-only items** — JE posted but no corresponding bank line yet (delayed clearing).

See `TROUBLESHOOTING_GUIDE.md` → Reconciliation Won't Match Transactions.

---

## Audit & Compliance

### What's the audit trail for?

The audit trail at `backend/audit_trails/audit_log.jsonl` is your evidence that:

- Every state change was made by a known, authorized user
- The chain hasn't been tampered with (cryptographic hash chain)
- Segregation of duties was actually applied (different people did upload, approve, post)
- Overrides have a documented business reason

Auditors love this. A clean audit trail typically shaves days off the annual audit fieldwork.

### How long are records retained?

| Record | Retention |
|--------|-----------|
| Audit trail | 7 years |
| Source invoice PDFs | 7 years |
| JE PDF receipts | 7 years |
| Bank statements (via Plaid) | 7 years |
| User accounts | Forever (disabled, not deleted, to preserve audit attribution) |

The 7-year window matches IRS recommendations for nonprofit tax records. Consult counsel for state-specific rules.

### Can I delete an old invoice for privacy reasons?

The invoice PDF and metadata cannot be deleted while within the retention window — that would break the audit trail. After 7 years, EIME's archival tool moves them to cold storage. For active GDPR-style requests, EIME exports a copy of all references to a subject without altering the trail.

### Who has access to my data?

Within EIME: only users you've explicitly created and assigned roles to.

External integrations:

- **Plaid** can read balances and transactions on linked accounts (read-only).
- **ACS Realm** receives posted JEs (write-only from EIME's side).
- **Anthropic** receives invoice text for LLM-based agent reasoning (no PII flagged for retention; see Anthropic's data policy).
- **Your SMTP provider** sees outgoing emails (subject + body of approval requests).

You control these via `.env` and can disconnect any of them without losing your historical data in EIME.

---

## Operational Limits

### How many invoices per month can EIME handle?

Reference deployment (4 vCPU, 8 GB RAM):

- **500 invoices/month** comfortably
- **2,000 invoices/month** with model warm-cache and PostgreSQL backend
- Beyond that, scale horizontally — multiple worker processes behind nginx

### How many users?

No hard limit. Tested with 50 active users; scales to hundreds with PostgreSQL backend.

### How many linked bank accounts?

Plaid free tier: typically 5–10 accounts. Production tier: unlimited. EIME has no internal cap.

### How many approval chain rules?

No hard limit. Realistically, parishes have 5–20 rules covering all the common GL patterns.

### What's the largest invoice EIME has handled?

Tested up to **500-line** invoices (think: large catering or school-supply orders). Above that, JE may exceed ACS's per-JE line limit; EIME splits into multiple sub-JEs.

### What's the maximum approved payment amount?

No technical maximum. The authority matrix sets the dollar caps you've configured. Most parishes cap `TREASURER_ADMIN` at $25K single / $100K monthly cumulative, with dual-signature above $10K — but this is configuration, not a hard limit.

---

## Cross-References

- Setting up the system the first time: `INITIAL_SETUP.md`
- Daily/weekly/monthly tasks: `OPERATIONS_MANUAL.md`
- When something breaks: `TROUBLESHOOTING_GUIDE.md`
- Roles and access: `ROLES_AND_PERMISSIONS.md`
- Security details: `SECURITY_BEST_PRACTICES.md`
