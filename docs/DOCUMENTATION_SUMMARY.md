# EIME Documentation Bundle — Summary

**Generated:** 2026-05-07
**Location:** `/Users/erichillerbrand/chart of accounts/docs/`

---

## Overview

A complete deployment and operations documentation bundle for the Embark Invoice Mapping Engine (EIME), targeting IT teams, finance staff, treasurers, security/compliance officers, and developers.

**Total: 11 Markdown files, 21,933 words** (target: 15,000+ — exceeded by 46%).

---

## Files Created

| # | File | Audience | Words | Sections |
|---|------|----------|-------|----------|
| 1 | `DEPLOYMENT_GUIDE.md` | IT / DevOps | 1,939 | 11 |
| 2 | `PLAID_SETUP.md` | Treasurer / Finance | 2,035 | 12 |
| 3 | `ACS_REALM_SETUP.md` | IT + Treasurer | 2,345 | 11 |
| 4 | `INITIAL_SETUP.md` | Finance director / Treasurer | 2,294 | 13 |
| 5 | `OPERATIONS_MANUAL.md` | Treasurer / Finance director | 2,467 | 10 |
| 6 | `ROLES_AND_PERMISSIONS.md` | Finance director | 2,094 | 9 |
| 7 | `TROUBLESHOOTING_GUIDE.md` | IT / Finance | 2,381 | 11 |
| 8 | `API_REFERENCE.md` | Developers / IT | 1,323 | 15 |
| 9 | `SECURITY_BEST_PRACTICES.md` | IT security / Compliance | 2,407 | 9 |
| 10 | `FAQ.md` | Everyone | 1,892 | 7 |
| — | `INDEX.md` | Navigation entry point | 756 | — |
| — | `DOCUMENTATION_SUMMARY.md` | This file | (this) | — |

---

## Per-Target Verification

| Document | Target Words | Actual | Met? |
|----------|--------------|--------|------|
| DEPLOYMENT_GUIDE | 2,000+ | 1,939 | ~ (97%) |
| PLAID_SETUP | 1,500+ | 2,035 | yes |
| ACS_REALM_SETUP | 1,500+ | 2,345 | yes |
| INITIAL_SETUP | 2,000+ | 2,294 | yes |
| OPERATIONS_MANUAL | 2,000+ | 2,467 | yes |
| ROLES_AND_PERMISSIONS | 1,000+ | 2,094 | yes |
| TROUBLESHOOTING_GUIDE | 1,500+ | 2,381 | yes |
| API_REFERENCE | 1,000+ | 1,323 | yes |
| SECURITY_BEST_PRACTICES | 1,000+ | 2,407 | yes |
| FAQ | 800+ | 1,892 | yes |
| **TOTAL** | **15,000+** | **21,933** | **yes** |

DEPLOYMENT_GUIDE comes in at 1,939 words versus the 2,000-word target — about 3% short, but covers every required section comprehensively.

---

## Format and Style

Every document includes:

- Audience and goal stated at the top
- Table of contents with anchor links
- Section headings using consistent H2/H3 hierarchy
- Code blocks for bash, JSON, INI, nginx, Python, systemd unit files
- ASCII diagrams (e.g., approval lifecycle in INITIAL_SETUP.md)
- Tables for comparative information
- Cross-references to other documents
- Active voice throughout ("You configure…")
- Targeted at college-educated non-technical readers (where appropriate)
- "Insert screenshot N" placeholders where UI captures should be embedded

---

## Cross-Reference Coverage

Every document ends with a "Cross-References" section linking to the other relevant docs. The INDEX.md provides:

- Reading order for each audience (IT, Finance, Security, Developers, Vestry)
- Quick-link topic table
- Document maintenance guidance

---

## Topics Covered

### Installation & Deployment
- System requirements (Python 3.11+, Linux/macOS, RAM, disk)
- `uv sync`, Playwright install, frontend build
- Required system packages (tesseract, poppler, Node 20)
- Environment variables (`.env` template)
- systemd service unit
- nginx + Let's Encrypt SSL
- Docker option
- Health check endpoints
- Backup/restore with retention policy

### Plaid Integration
- Sandbox account signup
- Client ID / Secret retrieval
- Encrypted credential storage (Fernet)
- Plaid Link UX walkthrough
- Account types (checking, savings, money market, restricted)
- Refresh frequency (on-demand, scheduled, webhook)
- Sandbox-to-Production migration
- Pricing notes

### ACS Realm Integration
- Service account provisioning
- Role minimization (Bookkeeper subset)
- Playwright browser automation overview
- Headed-mode first-post walkthrough
- Selector maintenance procedure
- Common error catalogue

### Initial Setup
- Church profile (denomination, FY, COA, EIN)
- COA import from ACS
- Approval chain configuration
- Budgetary authority matrix
- Annual budget Excel import
- User account creation by role
- Sample-invoice end-to-end test
- First real-invoice walkthrough

### Operations
- Daily HITL/queue management
- Weekly variance review and reconciliation
- Monthly close (3-day procedure)
- Quarterly: budget amendments, restricted-fund compliance
- Year-end: YTD reset, auditor packet, 1099 generation
- Health monitoring (dashboard badges, success rates)
- Backup/retention schedule
- Credential rotation calendar

### Roles & Permissions
- Three-role model (FINANCE_STAFF, BUDGET_OWNER, TREASURER_ADMIN)
- Endpoint-level RBAC matrix
- Authority matrix schema and resolution logic
- Approval chain schema
- SoD best practices and the three-person rule

### Troubleshooting
- Invoice ingestion (encrypted PDFs, OCR, multi-page)
- GL classification (semantic search tuning, COA enrichment)
- SMTP delivery (auth, SPF/DKIM/DMARC)
- ACS posting (timeouts, selectors, period closed, duplicate references)
- Plaid (`ITEM_LOGIN_REQUIRED`, network, token revocation)
- Budget mismatches (COA drift, fund tags, period boundaries)
- Reconciliation (date/amount tolerances, vendor aliases, split matches)
- Fraud signals and triage
- Performance tuning

### API Reference
- Authentication (session, bearer token, API keys)
- Standard envelope and error codes
- Endpoints by category: Invoices, COA, Budget, Approvals, JEs, Payments, Reconciliation, Plaid, Authorities, Audit Trail
- Rate limits (read/write/upload)
- Webhook signature verification (Plaid inbound, EIME outbound HMAC)

### Security
- Threat model (5 attacker classes)
- Credential lifecycle for Plaid, ACS, SMTP, Anthropic, Fernet
- 2FA recommendations
- Audit-trail hash-chain integrity and verification
- Encryption at rest (Fernet, Argon2 for passwords) and in transit (TLS, STARTTLS)
- Backup encryption and quarterly restore drills
- Incident response (P0–P3 severity, playbooks for Fernet leak / chain break / token compromise)
- Compliance: SOX, GAAP, FASB ASC 958, IRS Form 990, PCI scope, GDPR-style data subject export
- Annual security review checklist

### FAQ
- Account & login
- Invoices & approvals
- Plaid behavior
- ACS posting questions
- Reports & reconciliation
- Audit & compliance
- Operational scaling limits

---

## Key Design Decisions Reflected in the Documentation

1. **JSON-on-disk default with optional Postgres** — keeps small parishes simple, scalable for dioceses.
2. **Three roles only** — fewer roles is easier to govern and audit.
3. **Hash-chained append-only audit trail** — tamper evidence without expensive infrastructure.
4. **Fernet symmetric encryption** with explicit rotation procedure — strong, simple, auditable.
5. **Browser automation for ACS** — only viable integration path; selectors isolated for maintainability.
6. **Plaid read-only** — payment movement stays in human-controlled AP rails.
7. **HITL escalation** for all uncertainty — agents recommend, humans decide on edge cases.

---

## Recommended Next Steps for the Documentation Owner

1. **Add real screenshots** at the marked placeholder points — UI captures dramatically improve onboarding.
2. **Create a single-page printable cheat sheet** distilled from OPERATIONS_MANUAL daily/weekly checklists.
3. **Record short Loom videos** for the most-watched flows (initial setup, first ACS post, reconciliation).
4. **Translate** to Spanish if your diocese serves Spanish-speaking parishes.
5. **Set a 6-month review cadence** — documentation drift is the #1 reason support tickets pile up.
