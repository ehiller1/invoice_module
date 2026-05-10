# EIME Operations Manual

**Audience:** Treasurers, finance directors, and IT staff running EIME day-to-day, week-to-week, and through the year-end close.

**Goal:** A clear, repeatable cadence that keeps EIME healthy, your books current, and your audit trail clean.

---

## Table of Contents

1. [The EIME Operations Cadence](#the-eime-operations-cadence)
2. [Daily Checklist](#daily-checklist)
3. [Weekly Tasks](#weekly-tasks)
4. [Monthly Close-Out Procedures](#monthly-close-out-procedures)
5. [Quarter-End Tasks](#quarter-end-tasks)
6. [Year-End Tasks](#year-end-tasks)
7. [Ongoing Monitoring](#ongoing-monitoring)
8. [Backup and Retention Policies](#backup-and-retention-policies)
9. [Access Control and Credential Rotation](#access-control-and-credential-rotation-schedule)
10. [Audit Trail Review](#audit-trail-review-procedures)

---

## The EIME Operations Cadence

EIME is meant to run mostly autonomously. The treasurer's role shifts from **data entry** to **review and exception handling**. The cadence below assumes a single-parish deployment with 100–500 invoices per month. Adjust scope upward for larger dioceses.

| Cadence | Time Investment | Primary Owner |
|---------|-----------------|---------------|
| Daily | 10–15 minutes | Treasurer or AP clerk |
| Weekly | 30–45 minutes | Treasurer |
| Monthly | 2–4 hours over 3 days | Treasurer + Finance Committee |
| Quarterly | 1 hour | Treasurer |
| Annually | 4–8 hours over 1 week | Treasurer + auditor |

---

## Daily Checklist

Pick a consistent time each business day — many treasurers use 9 AM with their first coffee.

### 1. Open the EIME Dashboard

Navigate to **Dashboard**. Look for the four health badges in the header:

- **EIME Health** — green check if all background jobs ran in the last 24 h
- **Plaid** — green if all linked accounts refreshed today
- **ACS Realm** — green if last test login succeeded
- **SMTP** — green if the last approval email delivered

Any red badge → see [Ongoing Monitoring](#ongoing-monitoring) below.

### 2. Clear the HITL Queue

Click **HITL Queue**. This is where invoices land that EIME couldn't process automatically.

Each item shows:

- The invoice (PDF preview)
- Why it escalated (low GL confidence, fraud risk, budget overrun, fund restriction)
- The agent's recommendation
- Approve / Reject / Reroute buttons

Aim to clear the queue every business day. Items older than 5 business days get a yellow flag and an email reminder.

### 3. Approve Pending Items in Your Inbox

If you're a budget owner, check email for `[EIME] Approval Required: …` messages. Click **Approve** or **Reject** directly from email — no login required. The link is signed and expires after 7 days.

### 4. Confirm Yesterday's Posts

Click **Journal Entries → Posted Today** (filtered to yesterday). For each:

- Verify the JE number appears in ACS Realm.
- Spot-check that totals match the source invoice.

If a post failed (red status), see `TROUBLESHOOTING_GUIDE.md` → "JE posting to ACS fails".

### 5. Glance at Cash Position

The **Banking** tile shows current balances across all linked accounts. Confirm operating cash is above your minimum reserve threshold. Set the threshold in **Settings → Cash → Minimum Reserve**.

---

## Weekly Tasks

Schedule for Monday morning or Friday afternoon — pick what fits your workflow.

### 1. Budget Variance Review

Navigate to **Reports → Budget Variance**.

EIME shows YTD actual vs YTD budget for every GL, with three columns:

- Actual
- Budget
- Variance ($ and %)

Sort by **% over budget descending**. Investigate anything > 10% over.

For each significant variance:

- **Timing variance** (e.g., music director bought sheet music early): note in the comment field, leave alone.
- **True overrun**: discuss with the budget owner. EIME will block further approvals on that GL once the cap is hit unless overridden.
- **Coding error**: re-classify the offending JE. Use **JE → Edit → Reclassify** to push a correcting entry.

### 2. Reconciliation Spot-Check

Click **Reconciliation → Recent Matches**. EIME auto-matches Plaid transactions to JEs.

Look at the **Unmatched** tab. Two common cases:

- **Plaid has it, EIME doesn't** — bank cleared a transaction that wasn't in EIME. Add a JE manually or investigate (could be a bank fee, interest, or unauthorized debit).
- **EIME has it, Plaid doesn't** — JE posted but bank hasn't cleared yet (normal for ACH float; gives 5 business days before flagging).

### 3. Cash Flow Snapshot

Navigate to **Reports → Cash Flow → Last 7 Days**.

Glance at:

- Net change
- Largest single inflow / outflow
- Restricted-fund balance changes (any movement in/out of restricted funds is highlighted)

Alert any unusual restricted-fund activity to the rector or vestry treasurer.

### 4. Vendor Activity Check

**Reports → Vendors → New This Week** lists vendors that received their first payment this week. Confirm each is a known, approved vendor. Unfamiliar vendor + payment → potential fraud signal worth a quick verification call.

---

## Monthly Close-Out Procedures

Most parishes close on the 5th business day of the following month. EIME's tooling reduces close from days to hours, but the steps remain.

### Day 1 of Close: Prep

- [ ] **Stop accepting backdated invoices.** Ask staff to upload all prior-month invoices by EOD on the last business day of the month.
- [ ] **Refresh all Plaid balances** — `Banking → Refresh All`. Confirm timestamps are within the last 30 minutes.
- [ ] **Run pre-close report** — **Reports → Pre-Close** flags:
  - Invoices in HITL > 7 days
  - JEs not yet posted to ACS
  - Reconciliation variances > $10
  - Approval emails pending > 5 days

Resolve every flag before continuing.

### Day 2 of Close: JE Reconciliation

- [ ] **Match all JEs to source invoices.** **Reports → JE Audit → Last Month** lists every posted JE with a link to its source invoice. Review the unmatched list (should be very small — usually only manual JEs for adjustments).
- [ ] **Verify all manual JEs** have memos and supporting documentation attached (PDF receipts, board minutes for unusual entries).
- [ ] **Fund balance check** — restricted-fund debits must come from restricted-fund credits. EIME enforces this at posting time, but a final review covers reclassification edge cases.

### Day 3 of Close: Bank Reconciliation

- [ ] **Run formal reconciliation** for each operating account:
  - Navigate to **Reconciliation → Reconcile**.
  - Pick the account and the period (last calendar month).
  - EIME pulls the bank statement closing balance from Plaid, your GL closing balance from EIME, and any outstanding items.
  - The variance should be the sum of outstanding checks + deposits in transit.
- [ ] **Print reconciliation report** as PDF and file with the month's audit packet.
- [ ] **Sign off** — treasurer initials confirm the reconciliation is complete. EIME logs the sign-off to the audit trail.

### Day 4–5: Variance Reporting & Distribution

- [ ] **Generate monthly financial reports**:
  - Statement of Activities (Income Statement)
  - Statement of Financial Position (Balance Sheet)
  - Budget vs Actual (full-year, with month and YTD)
  - Restricted-fund activity
- [ ] **Email to vestry / finance committee** with a 2–3 sentence narrative on highlights and surprises.
- [ ] **Lock the period** in EIME via **Settings → Periods → Close Period**. After close, JEs cannot be backdated to that period without a TREASURER_ADMIN override. This protects the reconciled state.

---

## Quarter-End Tasks

Performed at end of Q1, Q2, Q3 (Q4 is rolled into year-end below).

### 1. Budget Amendment (If Needed)

If actual is consistently over/under budget on a GL by 20%+, the vestry may approve a **budget amendment** mid-year.

- Navigate to **Settings → Budget → Amendment**.
- Adjust the affected line items.
- Attach the meeting minutes PDF authorizing the change.
- The original budget is preserved for variance reporting; the amended budget becomes the active baseline going forward.

### 2. Restricted Fund Compliance Check

For each restricted fund:

- Run **Reports → Funds → Restricted Activity**.
- Confirm every disbursement matches the donor's intent (e.g., music fund used for sheet music, organ tuning — not for general operating).
- Document compliance review in the audit packet.

This is a key ASC 958 obligation. EIME flags any disbursement that looks suspicious (e.g., GL coded `5800-property` paid from restricted music fund) but does not block — that's a treasurer judgment call.

### 3. Vendor 1099 Pre-Check (Q4 only)

In Q4, run **Reports → 1099 Pre-Check** to identify vendors approaching the $600 threshold. Confirm you have a W-9 on file for each. Chase down missing W-9s in early December — you don't want to do it in January.

---

## Year-End Tasks

Plan for a full week of focused effort. Coordinate with your auditor and bookkeeper.

### Week 1 of January (or your fiscal new year)

- [ ] **Final monthly close** for December (or your last fiscal month).
- [ ] **YTD reset** — EIME automatically rolls YTD counters at fiscal year-end based on **Settings → Church Profile → Fiscal Year Start**. Confirm the rollover ran cleanly:
  - YTD budget actuals reset to zero.
  - Prior year is archived to `backend/data/archives/<year>/`.
  - Audit-trail chain hashes the year-end state for tamper evidence.
- [ ] **Generate year-end reports**:
  - Full-year Statement of Activities
  - Full-year Statement of Financial Position
  - Full-year Budget vs Actual
  - Full-year Restricted Fund Activity
  - Vendor 1099 worksheet
- [ ] **Export full audit trail** to a permanent archive: **Reports → Audit Trail → Export**. Save PDF + JSONL to your records-retention system.
- [ ] **Archive PDFs** — copy `backend/audit_pdfs/` to permanent storage. These are the signed receipts for every JE posted that year.

### Week 2: Auditor Prep

- [ ] **Generate auditor packet** — **Reports → Auditor Packet** bundles:
  - General ledger
  - Trial balance
  - Bank reconciliations
  - Selected JE samples with source invoices
  - Audit trail export (hash-chained)
  - User-access list (who had what role when)
- [ ] **Verify the audit-trail chain** — `uv run python -m backend.tools.verify_audit_chain`. Output should be `OK: chain intact across N entries`.

### Week 3: 1099 Filing

- [ ] **Generate 1099-NEC forms** — **Reports → 1099 → Generate**.
- [ ] **Review** for accuracy (vendor name, EIN/SSN, amount).
- [ ] **File with IRS** by January 31. EIME exports the IRS-compatible XML — submit through your e-file provider.
- [ ] **Mail copies** to vendors by January 31.

### Week 4: System Review

- [ ] **Annual security review** (see `SECURITY_BEST_PRACTICES.md`).
- [ ] **Annual access review** — confirm every active user still needs the role they have. Disable departed staff.
- [ ] **Rotate Plaid Secret** and **ACS service account password**.
- [ ] **Test backup restore** in a sandbox environment to verify backups actually work.

---

## Ongoing Monitoring

EIME runs background jobs continuously. Monitor these signals.

### Health Endpoints

Configure your monitoring tool (UptimeRobot, Pingdom, Datadog) to poll:

- `GET /health` every 60 s — alert after 3 consecutive failures
- `GET /health/plaid` every 5 min — alert after 6 failures (30 min outage)
- `GET /health/acs` every 15 min — alert after 4 failures (1 hour)

### Plaid Connection Health

A green Plaid badge on the dashboard means **all** linked accounts refreshed today. Yellow means at least one account needs re-authentication (`ITEM_LOGIN_REQUIRED`). Red means the Plaid client itself is unreachable. See `PLAID_SETUP.md` → Troubleshooting.

### ACS Posting Success Rate

**Reports → System → ACS Post Success Rate** shows the daily ratio of successful to attempted JE posts. Healthy: 99%+. Drop below 95% → investigate. Most often due to:

- ACS UI changes (selector update needed)
- Service account password rotation overdue
- Period closed in ACS but not in EIME

### Approval Email Deliverability

**Reports → System → SMTP Deliverability** tracks bounce rate. Anything > 1% suggests an SPF/DKIM problem with the sending domain. Coordinate with your IT team to fix DNS records.

### Disk Usage

`backend/data/`, `backend/audit_trails/`, `backend/audit_pdfs/`, and `backend/uploads/` grow over time. Monitor the partition. At 80% full, archive year-N-2 data to cold storage.

---

## Backup and Retention Policies

| Asset | Frequency | Retention | Storage |
|-------|-----------|-----------|---------|
| `backend/data/*.json` | Daily | 90 days | On-site + off-site |
| `backend/audit_trails/audit_log.jsonl` | Hourly | 7 years | Immutable, off-site |
| `backend/audit_pdfs/*.pdf` | Daily | 7 years | Immutable, off-site |
| `backend/uploads/*.pdf` (raw invoices) | Daily | 7 years | Immutable, off-site |
| `.env` and Fernet key | On change | Forever | Password vault |
| Database (if Postgres) | Daily dump | 90 days | Off-site |

**Why 7 years?** IRS guidance for nonprofit tax records and most state-level audit retention rules. Confirm with your attorney for your jurisdiction.

**Why immutable?** A breach must not be able to silently rewrite history. Use S3 with object-lock, write-once optical media, or your diocese's records-retention service.

Test restores quarterly. A backup you've never restored is a wish, not a backup.

---

## Access Control and Credential Rotation Schedule

| Item | Cadence | Owner |
|------|---------|-------|
| EIME user passwords | 180 days | User + Treasurer admin |
| ACS Realm service account | Annually + on treasurer turnover | Diocesan admin |
| Plaid Secret | Annually | Treasurer |
| Fernet encryption key | Every 2 years (or after suspected exposure) | IT + Treasurer |
| SMTP credentials | On rotation by SMTP provider | IT |
| User-role review | Quarterly | Treasurer |
| Backup-system access keys | Annually | IT |

Calendar reminders for each. Document each rotation in a credential-rotation log (date, who rotated, new expiry).

---

## Audit Trail Review Procedures

The audit trail at `backend/audit_trails/audit_log.jsonl` is the source of truth for every state change in EIME.

### Monthly Review

On the 5th of each month:

1. Run **Reports → Audit Trail → Last Month**.
2. Filter by `actor != system` and look for:
   - **After-hours activity** — any human action between 8 PM and 7 AM is worth a glance.
   - **Override events** — `acs.post.override`, `payment.block.override`, `period.unlock` — confirm each has a documented business justification.
   - **Rejected approvals** — if the same user repeatedly rejects, dig in (training gap or vendor issue).

### Quarterly Verification

Once a quarter, verify the chain:

```bash
uv run python -m backend.tools.verify_audit_chain --since 2026-01-01
```

Expected output: `OK: 1234 entries, chain intact`. Any other output → escalate immediately, this is a tampering indicator.

### Annual Auditor Walkthrough

Before each annual audit:

1. Generate the **auditor packet** (see Year-End Tasks).
2. Walk the auditor through one randomly selected JE end-to-end:
   - Source PDF
   - Ingestion log entry
   - Classification entry
   - Approval entry (with approver name, time, IP)
   - Fund-check entry
   - Post entry (with ACS JE number)
   - Reconciliation entry (with bank statement reference)
3. The auditor confirms the chain of custody is complete.

This walkthrough usually takes 20 minutes and dramatically shortens audit fieldwork.

---

## Cross-References

- Underlying setup details: `INITIAL_SETUP.md`
- When something goes wrong: `TROUBLESHOOTING_GUIDE.md`
- Role responsibilities: `ROLES_AND_PERMISSIONS.md`
- Security expectations: `SECURITY_BEST_PRACTICES.md`
- Common questions for your finance committee: `FAQ.md`
