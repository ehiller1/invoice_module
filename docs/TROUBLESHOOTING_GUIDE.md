# EIME Troubleshooting Guide

**Audience:** IT and finance staff diagnosing problems in a running EIME deployment.

**Goal:** A practical lookup of symptoms → likely causes → concrete fixes for the issues most commonly reported.

---

## Table of Contents

1. [How to Diagnose Any Issue (General Approach)](#how-to-diagnose-any-issue-general-approach)
2. [Invoice Ingestion Fails](#invoice-ingestion-fails)
3. [GL Classification Confidence Too Low](#gl-classification-confidence-too-low)
4. [Approval Email Not Sent](#approval-email-not-sent)
5. [JE Posting to ACS Fails](#je-posting-to-acs-fails)
6. [Plaid Balance Check Fails](#plaid-balance-check-fails)
7. [Budget Comparison Shows Wrong Numbers](#budget-comparison-shows-wrong-numbers)
8. [Reconciliation Won't Match Transactions](#reconciliation-wont-match-transactions)
9. [High Fraud Risk Flagged](#high-fraud-risk-flagged)
10. [Performance and Slowness](#performance-and-slowness)
11. [Where to Get Help](#where-to-get-help)

---

## How to Diagnose Any Issue (General Approach)

Before jumping to a specific section below, do this:

### 1. Check the Health Dashboard

`https://eime.yourchurch.org/dashboard` — the four health badges (EIME, Plaid, ACS, SMTP) tell you immediately whether the issue is a single component or system-wide.

### 2. Check the Logs

```bash
sudo journalctl -u eime -n 200 --no-pager
```

Or, for more detail:

```bash
tail -200 /opt/eime/backend/main.log
```

Look for `ERROR` or `EXCEPTION` lines, especially around the timestamp of the failure.

### 3. Check the Audit Trail

Every state change is in `backend/audit_trails/audit_log.jsonl`. For a specific invoice:

```bash
grep "INV-7821" /opt/eime/backend/audit_trails/audit_log.jsonl | jq .
```

This shows the full lifecycle and where it stalled.

### 4. Reproduce in Isolation

If a specific invoice or vendor is failing, try uploading a fresh sample. If the sample succeeds, the issue is invoice-specific. If the sample also fails, the issue is system-wide.

---

## Invoice Ingestion Fails

**Symptoms:**

- Upload completes but invoice card shows `Status: Ingestion Failed`.
- Vendor, date, or total are missing or obviously wrong.
- Extracted line items are empty.

### Cause 1: PDF has no text layer (image-only scan)

Many vendors send scanned-image PDFs. Without OCR, no text can be extracted.

**Fix:**

EIME falls back to `pytesseract` (Tesseract OCR) automatically. If OCR also fails:

- Confirm `tesseract` is installed: `tesseract --version`
- Confirm the PDF has reasonable resolution (>= 200 DPI). Lower resolution OCR is unreliable.
- Re-scan the original at higher resolution if you have access to the source.

### Cause 2: Encrypted/password-protected PDF

`pypdf` raises `PdfReadError: File has not been decrypted`.

**Fix:**

Ask the vendor to send an unencrypted version. If you have the password, decrypt first:

```bash
qpdf --password=<pwd> --decrypt input.pdf output.pdf
```

### Cause 3: Multi-page PDF with merged invoices

Vendors sometimes send a single PDF containing multiple unrelated invoices. EIME assumes one invoice per upload.

**Fix:**

Split the PDF (e.g., with `pdftk` or any PDF tool) and upload each invoice separately.

### Cause 4: Layout EIME has never seen

Some vendors use unusual layouts (no clear vendor name in the header, totals in unexpected places).

**Fix:**

Open the invoice in EIME and click **Manual Edit** to type the values directly. EIME records the correction. After 5+ manual edits for the same vendor, EIME's ingestion model adapts.

### Cause 5: File too large

The default upload cap is 25 MB. Larger files are rejected.

**Fix:**

- Compress the PDF (most are under 5 MB once compressed).
- Or raise the limit in `.env`: `EIME_MAX_UPLOAD_MB=50`.

---

## GL Classification Confidence Too Low

**Symptoms:**

- Invoice routes to HITL with reason `low_classification_confidence`.
- The proposed GL looks plausible but score < 0.85.

### Why this happens

EIME's classifier uses semantic search over the COA descriptions. If the invoice text is too generic ("services rendered" with no other context) or your COA descriptions are sparse, the model can't pick a winner with high confidence.

### Fix 1: Enrich your COA descriptions

Open **Settings → Chart of Accounts → Edit**. For each commonly used GL, add 3–5 example phrases in the description field. For example, `5100-001-000 — Office Supplies` could include: "paper, toner, pens, printer ink, file folders, postage stamps".

Re-index the embeddings:

```bash
uv run python -m backend.tools.reindex_coa
```

### Fix 2: Tune the confidence threshold

In `backend/agents/config.py` or **Settings → Agents → Classification**, the default confidence threshold is `0.85`. If your COA is comprehensive and you trust the classifier, lower to `0.75`. If you've seen wrong classifications proposed with high confidence, raise to `0.90`.

### Fix 3: Train via corrections

Each time a TREASURER_ADMIN reclassifies an invoice in HITL, EIME stores the correction. After ~20 corrections per vendor, the classifier learns vendor-specific defaults.

To inspect learned mappings:

```bash
uv run python -m backend.tools.show_vendor_mappings
```

---

## Approval Email Not Sent

**Symptoms:**

- Invoice status is `Pending Approval` but the budget owner says they got nothing.
- No `email.sent` event in the audit trail.

### Cause 1: SMTP credentials wrong or expired

**Fix:**

Test SMTP directly:

```bash
uv run python -m backend.tools.test_smtp --to your-email@example.com
```

Common errors:

- `(535) Authentication failed` — password rotated, update `SMTP_PASSWORD` in `.env`
- `Connection refused` — wrong host or port; verify with your SMTP provider
- `TLS handshake failed` — provider requires STARTTLS; ensure `SMTP_USE_TLS=true`

### Cause 2: No matching approval chain

The invoice's GL doesn't match any chain pattern, so EIME doesn't know who to notify. It still escalates to HITL but doesn't send an approval email.

**Fix:**

Add a fallback chain `*` → `treasurer@yourchurch.org`. Every invoice should match at least the fallback.

### Cause 3: Approver's email is wrong

A typo in the chain (e.g., `musci@yourchurch.org`).

**Fix:**

Edit the chain. Bounced emails appear in **Reports → System → SMTP Bounces**.

### Cause 4: Email landed in spam

Approval emails contain signed action URLs that some spam filters dislike.

**Fix:**

- Configure SPF, DKIM, and DMARC for your sending domain. Coordinate with your IT team.
- Ask the approver to whitelist `eime@yourchurch.org`.
- For habitual issues, switch SMTP providers (SendGrid, Postmark, Mailgun all have good deliverability).

---

## JE Posting to ACS Fails

**Symptoms:**

- HITL queue shows `Status: Post Failed` after manual approval.
- An audit-trail entry `acs.post.failed` with details.

### Cause 1: Playwright timeout

ACS was slow to respond and the default 60-second per-step timeout was hit.

**Fix:**

- Increase `ACS_TIMEOUT_MS=120000` in `.env`.
- Re-attempt manually: **HITL → Retry Post**.

### Cause 2: ACS UI changed

A selector no longer matches. The screenshot at `backend/audit_trails/acs_failure_<timestamp>.png` will show the new UI.

**Fix:**

Update selectors in `backend/integrations/acs_realm/selectors.py` (full procedure in `ACS_REALM_SETUP.md` → Handling ACS UI Changes). Restart EIME, then **Retry Post**.

### Cause 3: Credentials expired

ACS requires periodic password change. EIME login fails.

**Fix:**

1. Manually log into ACS as the service account.
2. Set a new password (do not reuse).
3. Update EIME's stored credential.
4. Restart EIME.
5. Retry the failed posts.

### Cause 4: Period closed in ACS

The JE date falls in a period that's been closed in ACS.

**Fix:**

- Re-open the period in ACS, post, re-close. (Allowed by your finance policy.)
- Or change the JE date to the current open period and add a memo: "Originally dated YYYY-MM-DD, posted to current period due to ACS close."

### Cause 5: Account or fund retired

The GL or fund used in the JE no longer exists in ACS.

**Fix:**

Re-import the COA from ACS to EIME so the lists match. **Settings → Chart of Accounts → Import**.

### Cause 6: Duplicate JE reference

EIME's external reference number was already used. Usually means a prior post succeeded silently and EIME didn't capture the response.

**Fix:**

1. Search ACS for the JE manually (by reference or date+amount).
2. If it's there, mark the EIME invoice **Already Posted** and link the existing JE number.
3. If it's not, generate a new external reference and retry.

---

## Plaid Balance Check Fails

**Symptoms:**

- Payment release blocked with `Plaid balance check failed`.
- Banking dashboard shows red badge on a linked account.

### Cause 1: `ITEM_LOGIN_REQUIRED`

Bank requires re-authentication (90–180 day cycle).

**Fix:**

**Banking → Linked Accounts → Re-authenticate**. Complete the Plaid Link flow again. Historical data is preserved.

### Cause 2: Network outage to Plaid

Outbound HTTPS to `api.plaid.com` is blocked or timing out.

**Fix:**

```bash
curl -I https://api.plaid.com
```

If the curl fails too, the issue is with your network/firewall. Check egress rules. Plaid IPs are documented at <https://plaid.com/docs/api/whitelist/>.

### Cause 3: Access token revoked

The user clicked "Revoke" in the bank's online portal.

**Fix:**

Re-link from scratch (the old token is permanently dead). **Banking → Linked Accounts → Add Account**.

### Cause 4: Plaid Secret rotated but EIME not updated

You rotated the Plaid Secret in the dashboard but didn't update EIME.

**Fix:**

Update `PLAID_SECRET` in `.env`, restart EIME.

### Cause 5: Sandbox token used in production

`PLAID_ENV=production` but token was created in sandbox (or vice versa).

**Fix:**

Re-link in the correct environment. See `PLAID_SETUP.md` → Upgrading from Sandbox.

---

## Budget Comparison Shows Wrong Numbers

**Symptoms:**

- Budget vs Actual report shows variance that doesn't match your spreadsheet.
- A GL that hasn't been spent on shows non-zero actual.

### Cause 1: COA mismatch

Your imported budget references GL codes that don't exist in EIME's COA, or the codes drifted (e.g., `5100-001-000` vs `5100-001`).

**Fix:**

- Run **Reports → Budget → Validate**. EIME lists GL codes in the budget that don't appear in the COA.
- Re-export COA from ACS, re-import to EIME.
- Re-import the budget with corrected codes.

### Cause 2: Fund code missing

A JE was posted without a fund tag, so it didn't roll up to the right fund's variance.

**Fix:**

- Find the offending JE in **Journal Entries → Filter by Missing Fund**.
- Reclassify with the correct fund — EIME generates a correcting JE.

### Cause 3: Period boundary issue

JEs near month-end were posted with the wrong date (e.g., a March 31 invoice posted with an April 1 date).

**Fix:**

- Confirm JE dates match the invoice service period, not the date you happened to process them.
- Re-date the JE if within the still-open period.

### Cause 4: Budget amendment not applied

You amended the budget but the report still shows the original.

**Fix:**

- **Reports → Budget Variance → Settings → Use Amended Budget** toggle.
- Or re-import the amendment.

---

## Reconciliation Won't Match Transactions

**Symptoms:**

- A bank transaction sits in **Unmatched** for days.
- Or, EIME reports a JE as unmatched even though the bank cleared it.

### Cause 1: Date discrepancy

JE dated April 30, bank cleared May 2. EIME's matcher allows a 7-day window by default, so this should match — unless the dates are further apart (common with check float).

**Fix:**

- Increase tolerance: **Settings → Reconciliation → Date Window** to 14 days.
- Manually match: **Reconciliation → Unmatched → Match**.

### Cause 2: Amount mismatch (small variance)

Vendor charged $123.45 but cleared as $123.46 (banking rounding).

**Fix:**

- Set **amount tolerance** to $0.01 in reconciliation settings.
- Manually match anything inside tolerance.

### Cause 3: Memo / reference doesn't carry through

Bank statement shows "POS PURCHASE 04/15" rather than the vendor name.

**Fix:**

EIME has heuristics (vendor master matching by amount + date + bank-line keywords). If they fail:

- Manually match for the first occurrence.
- Add a vendor alias: **Vendors → Edit → Add Alias** (e.g., alias "POS PURCHASE 04/15" → "Costco"). Future occurrences match automatically.

### Cause 4: Bank merged multiple JE payments into one

You sent a single ACH file paying 5 invoices; bank shows one $4,200 debit.

**Fix:**

- Split-match in EIME: **Reconciliation → Unmatched → Split Match → Select multiple JEs**.
- Total of selected JEs must equal the bank line.

---

## High Fraud Risk Flagged

**Symptoms:**

- Invoice routes to HITL with `risk_score >= 0.7` and reason like:
  - `duplicate_invoice_number`
  - `unusual_vendor`
  - `amount_spike_vs_history`
  - `restricted_fund_violation`
  - `denomination_specific_rule`

### Triage steps

1. **Read the rationale.** Each flag has a human-readable explanation in the HITL detail panel.
2. **Verify the source PDF.** Compare to the original from the vendor's email — ensure it wasn't tampered with.
3. **Cross-check the vendor.** Same vendor, same invoice number, same amount — almost always a duplicate. Reject and tell AP.
4. **Check fund eligibility.** If the GL is `5500-music` paid from `Restricted-Building Fund`, that's wrong. Reroute the GL or the fund.
5. **Decide.** TREASURER_ADMIN can override with a memo. Some flags (denomination-specific bylaws) cannot be overridden — re-route or reject.

### Common false positives

- **Annual subscription renewal** triggers `amount_spike_vs_history` because it last hit a year ago. Review and approve normally; EIME learns this pattern after 2–3 years.
- **New vendor for a known service** triggers `unusual_vendor`. Verify W-9 on file, then approve.
- **End-of-year bonus payroll** triggers `amount_spike`. Approve with memo "annual bonus per board minutes YYYY-MM-DD".

---

## Performance and Slowness

### Symptom: Invoice ingestion takes > 60 s

Cause: ChromaDB embeddings model loading on first call after restart. This is normal (cold start). After the model is warm, expect 5–15 s per invoice.

**Fix:** Pre-warm by calling the classifier on startup. Set `EIME_PREWARM=true` in `.env`.

### Symptom: Dashboard slow to load

Cause: Reading hundreds of JSON files synchronously.

**Fix:**

- Move from JSON files to PostgreSQL (set `DATABASE_URL`).
- Archive year-N-2 invoices to cold storage: `uv run python -m backend.tools.archive_year --year 2024`.

### Symptom: ACS posting takes > 2 minutes

Cause: ACS's UI is slow at certain hours, or the JE has many lines.

**Fix:**

- Don't worry under 2 minutes. Increase timeout if needed.
- For very long JEs, EIME can split into multiple sub-JEs (set `ACS_MAX_LINES_PER_JE=20` in `.env`).

---

## Where to Get Help

When self-service troubleshooting doesn't resolve the issue:

1. **Capture diagnostics.** Run `uv run python -m backend.tools.diagnostics_bundle`. This produces a zip of recent logs, audit trail (last 24 h), config (with secrets redacted), and a system info report.
2. **Check the audit trail** for the affected invoice or JE — paste the timeline into your support request.
3. **Reach out to your EIME support contact** (your IT vendor, internal IT team, or the EIME maintainer for your deployment) with the bundle and timeline.
4. **For Plaid-specific issues:** Plaid support at <https://dashboard.plaid.com/support>.
5. **For ACS Realm issues:** ACS Technologies support — your diocesan admin will have the contract info.

Never paste secrets (Plaid Secret, ACS password, Fernet key) into a support ticket. EIME's diagnostics bundle redacts them automatically — confirm before sending.

---

## Cross-References

- Initial setup: `INITIAL_SETUP.md`
- Day-2 operations and monitoring: `OPERATIONS_MANUAL.md`
- ACS-specific deep dive: `ACS_REALM_SETUP.md`
- Plaid-specific deep dive: `PLAID_SETUP.md`
- Security incident response: `SECURITY_BEST_PRACTICES.md`
