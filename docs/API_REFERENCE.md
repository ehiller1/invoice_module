# EIME API Reference

**Audience:** Developers and IT staff integrating with EIME or building custom dashboards / automations on top of it.

**Goal:** A complete reference of EIME's HTTP endpoints, authentication, request and response shapes, and webhook signatures.

---

## Table of Contents

1. [Base URL and Conventions](#base-url-and-conventions)
2. [Authentication](#authentication)
3. [Error Codes](#error-codes)
4. [Rate Limiting](#rate-limiting)
5. [Endpoints: Invoices](#endpoints-invoices)
6. [Endpoints: GL Codes (Chart of Accounts)](#endpoints-gl-codes-chart-of-accounts)
7. [Endpoints: Budget](#endpoints-budget)
8. [Endpoints: Approvals](#endpoints-approvals)
9. [Endpoints: Journal Entries](#endpoints-journal-entries)
10. [Endpoints: Payments](#endpoints-payments)
11. [Endpoints: Reconciliation](#endpoints-reconciliation)
12. [Endpoints: Plaid](#endpoints-plaid)
13. [Endpoints: Authorities](#endpoints-authorities)
14. [Endpoints: Audit Trail](#endpoints-audit-trail)
15. [Webhook Signatures](#webhook-signatures)

---

## Base URL and Conventions

Production: `https://eime.yourchurch.org/api`
Development: `http://localhost:8000/api`

All requests and responses are JSON unless stated. Timestamps are ISO 8601 UTC (e.g., `2026-05-07T14:23:01.412Z`). Money amounts are JSON numbers in **dollars** with up to 2 decimal places (e.g., `1234.56`). GL codes are strings.

Standard response envelope:

```json
{
  "ok": true,
  "data": { ... },
  "meta": { "ts": "2026-05-07T14:23:01.412Z", "request_id": "req_abc123" }
}
```

On error:

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_GL_CODE",
    "message": "GL code 5100-001-999 not found in COA",
    "details": { "gl_code": "5100-001-999" }
  },
  "meta": { "ts": "...", "request_id": "..." }
}
```

---

## Authentication

EIME uses **session cookies** for the web UI and **bearer tokens** for API clients. Programmatic clients must obtain a token first.

### Login (obtain token)

```
POST /api/auth/login
Content-Type: application/json

{ "email": "treasurer@yourchurch.org", "password": "..." }
```

Response:

```json
{
  "ok": true,
  "data": {
    "token": "eyJhbGciOi...",
    "expires_at": "2026-05-08T14:23:01.412Z",
    "role": "TREASURER_ADMIN"
  }
}
```

### Use the token

```
GET /api/invoices
Authorization: Bearer eyJhbGciOi...
```

Tokens last 24 hours. Refresh via:

```
POST /api/auth/refresh
Authorization: Bearer <existing token>
```

### API keys (server-to-server)

For non-interactive clients (e.g., a nightly script), generate a long-lived API key:

```
POST /api/auth/keys
Authorization: Bearer <admin token>
{ "name": "nightly-export", "scopes": ["read:invoices", "read:reports"] }
```

API keys carry their own RBAC scopes (subset of the issuing user's role).

---

## Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `UNAUTHORIZED` | 401 | Missing or invalid token |
| `FORBIDDEN` | 403 | Authenticated but role/scope insufficient |
| `NOT_FOUND` | 404 | Resource doesn't exist |
| `INVALID_INPUT` | 400 | Validation error; see `details` |
| `INVALID_GL_CODE` | 400 | GL not in COA |
| `INVALID_FUND` | 400 | Fund not configured |
| `BUDGET_EXCEEDED` | 409 | Approval would exceed authority cap |
| `FUND_RESTRICTED` | 409 | Source fund is restricted; admin override required |
| `DUPLICATE_INVOICE` | 409 | Invoice number already ingested |
| `PERIOD_CLOSED` | 409 | Posting period locked |
| `PLAID_ERROR` | 502 | Plaid API returned an error; see `details.plaid_error_code` |
| `ACS_ERROR` | 502 | ACS automation failed; see `details.acs_phase` |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unexpected; check audit log |

---

## Rate Limiting

Default limits per token:

| Scope | Limit |
|-------|-------|
| Read endpoints | 600 / minute |
| Write endpoints (POST/PUT/DELETE) | 60 / minute |
| `/api/invoices/upload` | 30 / hour |
| `/api/plaid/balances/refresh` | 100 / day |

Headers on every response:

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset` (epoch seconds)

When exceeded, response is HTTP 429 with `Retry-After` header.

---

## Endpoints: Invoices

### `GET /api/invoices`

List invoices. Query params: `status` (`pending|approved|paid|rejected`), `vendor`, `from`, `to`, `limit`, `cursor`.

Response:

```json
{ "ok": true, "data": { "items": [ { ...InvoiceSummary } ], "next_cursor": "..." } }
```

### `GET /api/invoices/{id}`

Full invoice detail including extracted lines, classification, risk flags, approval history.

### `POST /api/invoices/upload`

Multipart upload of a PDF.

```
POST /api/invoices/upload
Content-Type: multipart/form-data
file=<pdf>
```

Returns the new invoice's `id`. Async pipeline kicks off; poll `GET /api/invoices/{id}` for status.

### `POST /api/invoices/{id}/approve`

```json
{ "memo": "Routine office supplies", "override_flags": [] }
```

Requires `BUDGET_OWNER` (within their scope) or `TREASURER_ADMIN`. Returns updated invoice.

### `POST /api/invoices/{id}/reject`

```json
{ "reason": "Duplicate of INV-7798" }
```

### `POST /api/invoices/{id}/reclassify`

Admin-only; pushes a correcting JE.

```json
{ "new_gl_code": "5100-002-000", "new_fund": "General", "memo": "Reclassified per policy" }
```

---

## Endpoints: GL Codes (Chart of Accounts)

### `GET /api/coa`

Returns full COA.

```json
{
  "items": [
    { "code": "5100-001-000", "name": "Office Supplies", "type": "Expense", "fund": "General", "active": true }
  ]
}
```

### `GET /api/coa/{code}`

Single GL detail including embedding metadata.

### `POST /api/coa/import`

Multipart CSV import. Admin-only.

### `POST /api/coa/{code}`

Update fields (name, description, active flag). Admin-only.

---

## Endpoints: Budget

### `GET /api/budget?fy=2026`

Returns the active budget for the fiscal year.

### `GET /api/budget/variance?fy=2026&period=2026-04`

YTD actual vs YTD budget per GL.

### `POST /api/budget/import`

Multipart Excel import. Admin-only.

### `POST /api/budget/amendment`

```json
{
  "fy": 2026,
  "changes": [
    { "gl_code": "5500-100-000", "month": "jul", "delta": 500, "rationale": "Sheet music for Easter" }
  ],
  "minutes_pdf": "<base64>"
}
```

---

## Endpoints: Approvals

### `GET /api/approvals/chains`

Returns approval-chain configuration.

### `POST /api/approvals/chains`

```json
{ "gl_pattern": "5500-*", "primary": "music@example.org", "backup": "treasurer@example.org", "threshold": 0 }
```

### `GET /api/approvals/pending`

Items awaiting the current user's action.

### `POST /api/approvals/email-action`

Validates a signed approval link from email and applies the decision. Used by the email-button flow.

---

## Endpoints: Journal Entries

### `GET /api/journal-entries`

Filterable list.

### `GET /api/journal-entries/{id}`

Detail including ACS reference and PDF receipt URL.

### `POST /api/journal-entries/{id}/post`

Triggers ACS posting. Admin-only.

### `POST /api/journal-entries/manual`

Create a manual JE (no source invoice).

```json
{
  "date": "2026-04-30",
  "memo": "Bank fee April",
  "lines": [
    { "gl_code": "6700-001-000", "fund": "General", "debit": 12.50 },
    { "gl_code": "1010-001-000", "fund": "General", "credit": 12.50 }
  ]
}
```

---

## Endpoints: Payments

### `GET /api/payments`

List payment records (each AP invoice generates a payment).

### `POST /api/payments/{id}/release`

Performs Plaid balance check and unblocks payment for AP rail. Admin-only.

### `POST /api/payments/{id}/mark-paid`

```json
{ "method": "ach", "reference": "ACH-20260507-0001", "cleared_date": "2026-05-08" }
```

---

## Endpoints: Reconciliation

### `GET /api/reconciliation?account_id=...&period=2026-04`

Returns matched JEs, unmatched bank lines, unmatched JEs, and reconciliation status.

### `POST /api/reconciliation/match`

```json
{ "bank_line_id": "...", "je_ids": ["..."], "memo": "Manual match" }
```

### `POST /api/reconciliation/{id}/sign-off`

Treasurer signs off on the period reconciliation.

---

## Endpoints: Plaid

### `POST /api/plaid/link/token`

Returns a `link_token` for the frontend to initialize Plaid Link.

### `POST /api/plaid/link/exchange`

```json
{ "public_token": "..." }
```

Server exchanges for `access_token`, encrypts, stores. Admin-only.

### `GET /api/plaid/balances`

```json
{
  "accounts": [
    { "id": "...", "name": "Operating", "mask": "...4521", "type": "depository", "subtype": "checking", "current": 48732.10, "available": 48732.10, "as_of": "2026-05-07T14:00:00Z" }
  ]
}
```

### `POST /api/plaid/balances/refresh`

Forces an on-demand refresh.

### `POST /api/plaid/webhook`

Plaid pushes events here (transactions updated, item login required, etc.). See [Webhook Signatures](#webhook-signatures).

---

## Endpoints: Authorities

### `GET /api/authorities`

Returns the budgetary authority matrix.

### `POST /api/authorities`

```json
{
  "role": "BUDGET_OWNER",
  "gl_pattern": "5500-*",
  "max_single": 1000,
  "max_monthly_cumulative": 5000,
  "requires_dual_signature": false
}
```

Admin-only.

### `DELETE /api/authorities/{id}`

Admin-only. Soft delete (logged to audit trail).

---

## Endpoints: Audit Trail

### `GET /api/audit-trail`

Filterable: `actor`, `action`, `resource`, `from`, `to`. Non-admins see only their own actions.

### `GET /api/audit-trail/export`

Downloads JSONL of the audit trail. Admin-only.

### `GET /api/audit-trail/verify`

Verifies the hash chain.

```json
{
  "entries": 12345,
  "ok": true,
  "first_break": null
}
```

---

## Webhook Signatures

EIME signs outgoing webhooks (if configured) and verifies incoming Plaid webhooks.

### Plaid → EIME

Plaid signs webhooks with a JWT in the `Plaid-Verification` header. EIME's handler verifies using `/webhook_verification_key/get`. Pseudocode:

```python
import jwt, requests
key_id = jwt.get_unverified_header(token)["kid"]
key = requests.post("https://api.plaid.com/webhook_verification_key/get",
                    json={"client_id": ..., "secret": ..., "key_id": key_id}).json()["key"]
payload = jwt.decode(token, key=key, algorithms=["ES256"])
assert payload["request_body_sha256"] == sha256(raw_body)
```

A failed signature returns 401 and is logged to the audit trail.

### EIME → External

If you configure outbound webhooks (e.g., to Slack on approval events), EIME signs the body with HMAC-SHA256 using `EIME_WEBHOOK_SIGNING_SECRET`. Header:

```
X-EIME-Signature: t=1714842181,v1=4f8c2a1b9e7d4c0012345678abcdef...
```

To verify:

```python
import hmac, hashlib
parts = dict(p.split("=", 1) for p in header.split(","))
expected = hmac.new(secret.encode(), f"{parts['t']}.{body}".encode(), hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, parts["v1"])
```

Reject if `t` is more than 5 minutes old (prevents replay).

---

## Cross-References

- Authentication overview: `SECURITY_BEST_PRACTICES.md`
- Role-by-endpoint enforcement: `ROLES_AND_PERMISSIONS.md`
- When endpoints fail: `TROUBLESHOOTING_GUIDE.md`
- Plaid webhook setup: `PLAID_SETUP.md`
