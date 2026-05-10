# Roles and Permissions

**Audience:** Finance directors and treasurers who need to decide who can do what in EIME.

**Goal:** Confidently assign roles that uphold segregation of duties (SoD), match your bylaws, and pass an annual audit.

---

## Table of Contents

1. [The Three Roles at a Glance](#the-three-roles-at-a-glance)
2. [FINANCE_STAFF Role](#finance_staff-role)
3. [BUDGET_OWNER Role](#budget_owner-role)
4. [TREASURER_ADMIN Role](#treasurer_admin-role)
5. [Creating User Accounts and Assigning Roles](#creating-user-accounts-and-assigning-roles)
6. [Role-Based Access Control by Endpoint](#role-based-access-control-by-endpoint)
7. [Budgetary Authority Matrix](#budgetary-authority-matrix)
8. [Approval Chain Configuration](#approval-chain-configuration)
9. [Best Practices for Delegation and Segregation of Duties](#best-practices-for-delegation-and-segregation-of-duties)

---

## The Three Roles at a Glance

EIME ships exactly three roles. This is intentional — fewer roles is easier to govern and audit.

| Role | Read | Approve (within cap) | Configure | Post JEs | Override |
|------|:----:|:-------------------:|:---------:|:--------:|:--------:|
| FINANCE_STAFF | ✓ | — | — | — | — |
| BUDGET_OWNER | ✓ | ✓ | — | — | — |
| TREASURER_ADMIN | ✓ | ✓ | ✓ | ✓ | ✓ |

There is no "super admin" beyond `TREASURER_ADMIN`. Cross-cutting actions (like deleting an audit-log entry) are not exposed at all — that protects your audit trail.

---

## FINANCE_STAFF Role

**Purpose:** Read-only visibility for staff who need to see the books but should not change them.

### Typical Holders

- Bookkeeper (preparing reports, but not approving)
- Finance committee members
- AP clerks who upload invoices but do not approve them
- The rector (if not separately a `BUDGET_OWNER` for clergy expenses)

### What They Can Do

- View all reports (P&L, balance sheet, budget vs actual, restricted-fund activity)
- View the HITL queue (read-only)
- View any individual invoice, JE, or payment
- View vendor history
- Upload invoices for processing (this triggers the agent pipeline)

### What They Cannot Do

- Approve or reject any invoice
- Configure the system (COA, budget, approval chains, users)
- Post JEs to ACS
- Re-classify GL codes
- Override blocks
- See encrypted credential fields (Plaid secret, ACS password — even masked)

### Notes

Staff holding this role can still **upload** invoices, which is what enables the AP clerk workflow: clerk uploads, the BUDGET_OWNER approves, the TREASURER_ADMIN posts. Three pairs of hands keep SoD clean.

---

## BUDGET_OWNER Role

**Purpose:** Department heads who own a slice of the budget — they approve invoices coded to their GL codes up to a configured dollar cap.

### Typical Holders

- Music director (owns `5500-*` music & worship GLs)
- Education director (owns `5400-*` Christian education GLs)
- Property committee chair (owns `5800-*` building & grounds GLs)
- Outreach committee chair (owns `5900-*` outreach GLs)
- Office manager (owns `5100-*` office supply GLs)

### What They Can Do

- Everything `FINANCE_STAFF` can do
- Approve or reject invoices that:
  - match a GL pattern they own (configured in their user record), AND
  - fall under their single-approval cap, AND
  - keep their monthly cumulative cap intact
- View their own approval history
- Add a memo when approving (required for invoices > $1,000)

### What They Cannot Do

- Approve invoices outside their assigned GL patterns
- Approve above their single-approval cap
- Override fund-restriction blocks (those go to `TREASURER_ADMIN`)
- Configure approval chains, budget, or COA
- Post JEs to ACS

### Configuring a Budget Owner

When creating a `BUDGET_OWNER` user, set:

- **Assigned GL Patterns** — list of patterns like `5500-*`, `5510-*`. Multiple are allowed.
- **Single Approval Cap** — dollar limit per invoice (e.g., $1,000)
- **Monthly Cumulative Cap** — total they can approve in a calendar month (e.g., $5,000)

If their cap is hit mid-month, EIME automatically routes their further approvals up to the `TREASURER_ADMIN`.

---

## TREASURER_ADMIN Role

**Purpose:** Top-level operator. Owns system configuration, exception handling, and posting.

### Typical Holders

- Treasurer (primary)
- Finance director (primary or backup)
- Vestry treasurer (backup)

### What They Can Do

- Everything `BUDGET_OWNER` can do — for **all** GL patterns and **without** caps (unless dual-signature is configured for amounts above $50K)
- Configure:
  - Church profile
  - Chart of accounts (import, edit, retire)
  - Budget (import, amend)
  - Approval chains
  - Authority matrix
  - Users and roles
  - Plaid integration
  - ACS Realm integration
  - SMTP settings
- Post JEs to ACS Realm
- Override:
  - Fund-restriction blocks (with required justification memo)
  - Budget overrun blocks
  - Payment release blocks (e.g., insufficient-funds warnings)
- Lock and unlock accounting periods
- Re-classify any GL code on any historical invoice (creates a correcting JE; cannot edit the original)
- Mark invoices as paid (with payment reference)
- Generate full audit-trail exports

### What They Cannot Do

- Edit or delete entries in `audit_trails/audit_log.jsonl` — the file is append-only and hash-chained. Even root-level OS access cannot do this without breaking the chain.
- Self-approve high-value items if dual-signature is configured (must come from a second `TREASURER_ADMIN`)

### Recommended Constraint

**Always have at least two `TREASURER_ADMIN` users.** This protects against:

- Single-point-of-failure on vacation or illness
- Self-approval on dual-signature items
- Lost credentials (a second admin can reset the first)

---

## Creating User Accounts and Assigning Roles

### Via UI

1. Log in as `TREASURER_ADMIN`.
2. Navigate to **Settings → Users → Add User**.
3. Fill the form:
   - **Email** (login identifier; must be unique)
   - **Full Name**
   - **Role** (one of the three)
   - **Assigned GL Patterns** (only for `BUDGET_OWNER`)
   - **Single Approval Cap** (only for `BUDGET_OWNER`)
   - **Monthly Cumulative Cap** (only for `BUDGET_OWNER`)
4. Click **Save**.
5. EIME emails the user a **set-password** link valid for 24 hours.

### Via CLI (Bootstrap or Recovery)

```bash
uv run python -m backend.tools.create_admin --email new-treasurer@yourchurch.org
```

This creates a `TREASURER_ADMIN` and emails the password-set link. Use this when no admin exists yet (initial deploy) or to recover from a locked-out admin.

### Disabling Users

Never delete users — that breaks audit-log foreign keys. Instead:

1. **Settings → Users → Edit → Disable**.
2. The user can no longer log in or receive approval emails.
3. Their historical actions remain attributed to them in the audit trail.

Disable departing staff on their last day. Disable role changes (e.g., demoted from `TREASURER_ADMIN`) at the moment of change, then create a new user with the new role.

---

## Role-Based Access Control by Endpoint

EIME enforces RBAC at every API endpoint. The table below summarizes the key routes (full reference in `API_REFERENCE.md`).

| Endpoint | FINANCE_STAFF | BUDGET_OWNER | TREASURER_ADMIN |
|----------|:-------------:|:------------:|:---------------:|
| `GET /api/invoices` | ✓ | ✓ | ✓ |
| `POST /api/invoices/upload` | ✓ | ✓ | ✓ |
| `POST /api/invoices/{id}/approve` | — | ✓ (within scope) | ✓ |
| `POST /api/invoices/{id}/reject` | — | ✓ (within scope) | ✓ |
| `POST /api/invoices/{id}/reclassify` | — | — | ✓ |
| `GET /api/journal-entries` | ✓ | ✓ | ✓ |
| `POST /api/journal-entries/{id}/post` | — | — | ✓ |
| `GET /api/budget` | ✓ | ✓ | ✓ |
| `POST /api/budget/import` | — | — | ✓ |
| `POST /api/budget/amendment` | — | — | ✓ |
| `GET /api/coa` | ✓ | ✓ | ✓ |
| `POST /api/coa/import` | — | — | ✓ |
| `GET /api/users` | — | — | ✓ |
| `POST /api/users` | — | — | ✓ |
| `GET /api/audit-trail` | ✓ (own actions only) | ✓ (own actions only) | ✓ (all) |
| `GET /api/audit-trail/export` | — | — | ✓ |
| `GET /api/plaid/balances` | ✓ | ✓ | ✓ |
| `POST /api/plaid/link` | — | — | ✓ |
| `POST /api/payments/{id}/release` | — | — | ✓ |
| `POST /api/periods/close` | — | — | ✓ |
| `POST /api/periods/unlock` | — | — | ✓ |

Any endpoint not listed defaults to `TREASURER_ADMIN`-only.

---

## Budgetary Authority Matrix

The authority matrix is configurable in **Settings → Approvals → Authority Matrix** and stored at `backend/data/budgetary_authority.json`. It encodes "**who can approve what, up to how much**".

### Schema

Each rule has:

- `role` — `BUDGET_OWNER` or `TREASURER_ADMIN`
- `gl_pattern` — wildcard glob (e.g., `5500-*`, `*`)
- `max_single` — dollar cap per invoice
- `max_monthly_cumulative` — dollar cap per calendar month
- `requires_dual_signature` — bool; if true, second approver from same role required
- `dual_signature_threshold` — dollar amount above which dual signature triggers

### Example

```json
[
  {
    "role": "BUDGET_OWNER",
    "gl_pattern": "5500-*",
    "max_single": 1000,
    "max_monthly_cumulative": 5000,
    "requires_dual_signature": false
  },
  {
    "role": "TREASURER_ADMIN",
    "gl_pattern": "*",
    "max_single": 25000,
    "max_monthly_cumulative": 100000,
    "requires_dual_signature": true,
    "dual_signature_threshold": 10000
  }
]
```

This matrix says: a music budget owner approves up to $1,000 per invoice and $5,000 per month within `5500-*`. The treasurer approves up to $25K but anything above $10K needs a second treasurer's signature.

### Resolution Logic

When an invoice arrives, EIME finds the most-specific matching rule for the approver's role and the invoice's GL. If the amount fits, the approval proceeds. If not, EIME escalates to the next-higher role.

---

## Approval Chain Configuration

The approval chain answers "**who gets the email**" for an invoice.

### Schema

Each chain entry maps a GL pattern to one or more approvers:

```json
[
  {"gl_pattern": "5500-*", "primary": "music@yourchurch.org", "backup": "treasurer@yourchurch.org", "threshold": 0},
  {"gl_pattern": "5800-*", "primary": "property@yourchurch.org", "backup": "treasurer@yourchurch.org", "threshold": 0},
  {"gl_pattern": "*",      "primary": "treasurer@yourchurch.org", "backup": null, "threshold": 0}
]
```

`threshold` lets you auto-approve below a small floor (typical $0–$50 for petty-cash-style items).

### Resolution Logic

1. EIME finds the most-specific pattern that matches the invoice's GL.
2. The primary approver receives the email.
3. If they don't act within 48 hours, EIME emails the backup.
4. If neither acts within 5 business days, the invoice escalates to HITL for treasurer review.

### Change Tracking

Every change to the chain is logged. **Settings → Approvals → Approval Chains → History** shows the diff timeline.

---

## Best Practices for Delegation and Segregation of Duties

### The Three-Person Rule

For any single transaction, at least three different people should be involved:

1. The **uploader** (often AP clerk, `FINANCE_STAFF`)
2. The **approver** (`BUDGET_OWNER` or `TREASURER_ADMIN`)
3. The **poster** (`TREASURER_ADMIN`, often a different one from the approver)

EIME does not enforce different humans across these steps — your bylaws and culture do. Configure roles so the most common path follows three people, and use audit reviews to verify.

### Don't Stack Roles on One Person

Avoid making the same person both a high-cap `BUDGET_OWNER` and the only `TREASURER_ADMIN`. They can self-approve their own departmental spending up to their cap, then post the JE themselves. That's an SoD violation.

If staffing is tight, at minimum require **dual signature** on amounts above a meaningful threshold (e.g., $5,000) so a second pair of eyes is forced.

### Approval Caps Reflect Risk Appetite

Calibrate caps to match what your finance committee considers material:

- A $200 cap on `BUDGET_OWNER` is too low and creates approval fatigue at `TREASURER_ADMIN`.
- A $25,000 cap on `BUDGET_OWNER` is too high and concentrates authority.
- $1,000–$5,000 single-approval caps are typical for parishes; 10× that for dioceses.

### Quarterly Access Review

Each quarter:

1. Export the user list (**Settings → Users → Export**).
2. Walk through with the rector or finance committee chair.
3. For each user, confirm role and caps still match their job.
4. Disable any user who left or changed roles.
5. Sign and file the review (auditors love seeing this).

### Onboarding and Offboarding Checklists

**Onboarding new staff:**

- [ ] Manager requests access in writing (email is fine)
- [ ] Treasurer creates user with minimum-needed role
- [ ] User completes set-password flow
- [ ] User completes a 30-minute walk-through with the treasurer
- [ ] First approval reviewed and discussed before going independent

**Offboarding departing staff (last day):**

- [ ] Disable EIME user account
- [ ] Reassign their GL patterns to backup approver
- [ ] Update approval-chain emails
- [ ] If they were `TREASURER_ADMIN`, rotate the ACS Realm service account password (they may know it)
- [ ] Note the change in the audit-review log

### Avoid Email Forwarding

Approval emails contain signed action links. If a budget owner forwards their email to someone else who clicks "Approve", **EIME records the original budget owner as the approver** — but the action wasn't really theirs. Train staff: never forward approval emails. If you can't approve, reroute through EIME's UI instead.

---

## Cross-References

- How to set up roles in the first place: `INITIAL_SETUP.md`
- Day-2 access reviews: `OPERATIONS_MANUAL.md`
- Encryption and credential management: `SECURITY_BEST_PRACTICES.md`
- API endpoints by role: `API_REFERENCE.md`
- Common access-related questions: `FAQ.md`
