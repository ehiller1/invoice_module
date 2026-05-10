# EIME Documentation Index

Welcome to the EIME (Embark Invoice Mapping Engine) documentation. This index lists all 10 setup and operations guides, with suggested reading orders for each audience.

---

## All Documents

| # | Document | Audience | Length |
|---|----------|----------|--------|
| 1 | [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) | IT / DevOps | ~2,200 words |
| 2 | [PLAID_SETUP.md](./PLAID_SETUP.md) | Treasurer / Finance | ~1,900 words |
| 3 | [ACS_REALM_SETUP.md](./ACS_REALM_SETUP.md) | IT + Treasurer | ~2,000 words |
| 4 | [INITIAL_SETUP.md](./INITIAL_SETUP.md) | Finance director / Treasurer | ~2,200 words |
| 5 | [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md) | Treasurer / Finance director | ~2,400 words |
| 6 | [ROLES_AND_PERMISSIONS.md](./ROLES_AND_PERMISSIONS.md) | Finance director | ~2,000 words |
| 7 | [TROUBLESHOOTING_GUIDE.md](./TROUBLESHOOTING_GUIDE.md) | IT / Finance | ~2,200 words |
| 8 | [API_REFERENCE.md](./API_REFERENCE.md) | Developers / IT integrators | ~1,400 words |
| 9 | [SECURITY_BEST_PRACTICES.md](./SECURITY_BEST_PRACTICES.md) | IT security / Compliance | ~2,200 words |
| 10 | [FAQ.md](./FAQ.md) | Everyone | ~1,500 words |

---

## Suggested Reading Orders

### For IT / DevOps Teams Deploying EIME

You're standing up a fresh EIME instance.

1. **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** — System requirements, install steps, environment configuration, SSL, Docker, health checks, backup strategy.
2. **[PLAID_SETUP.md](./PLAID_SETUP.md)** — Wire up Plaid for live bank balances.
3. **[ACS_REALM_SETUP.md](./ACS_REALM_SETUP.md)** — Wire up ACS Realm for JE posting.
4. **[SECURITY_BEST_PRACTICES.md](./SECURITY_BEST_PRACTICES.md)** — Harden the deployment before any real data flows.
5. **[TROUBLESHOOTING_GUIDE.md](./TROUBLESHOOTING_GUIDE.md)** — Bookmark for day-2 incidents.
6. **[API_REFERENCE.md](./API_REFERENCE.md)** — If you'll integrate with other systems.

**Estimated time investment:** 1–2 days for full deployment, including the Plaid + ACS connections.

---

### For Finance Staff (Treasurers, Directors)

You're configuring EIME for first-day use and operating it ongoing.

1. **[INITIAL_SETUP.md](./INITIAL_SETUP.md)** — Day-1 walkthrough: church profile, COA, budget, approval chains, first invoice end-to-end.
2. **[OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md)** — Daily / weekly / monthly / quarter-end / year-end cadence.
3. **[ROLES_AND_PERMISSIONS.md](./ROLES_AND_PERMISSIONS.md)** — Decide who gets which role and what cap.
4. **[FAQ.md](./FAQ.md)** — Quick answers for common staff questions.
5. **[TROUBLESHOOTING_GUIDE.md](./TROUBLESHOOTING_GUIDE.md)** — When something doesn't behave as expected.

**Estimated time investment:** Half-day for INITIAL_SETUP; OPERATIONS_MANUAL becomes your weekly reference.

---

### For Security and Compliance Officers

You're verifying EIME meets your governance bar.

1. **[SECURITY_BEST_PRACTICES.md](./SECURITY_BEST_PRACTICES.md)** — Threat model, credential lifecycle, audit trail integrity, incident response, compliance mapping (SOX, GAAP, ASC 958).
2. **[ROLES_AND_PERMISSIONS.md](./ROLES_AND_PERMISSIONS.md)** — RBAC and segregation of duties.
3. **[OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md)** — Audit trail review and quarterly access review procedures.
4. **[FAQ.md](./FAQ.md)** — Audit and compliance section.
5. **[API_REFERENCE.md](./API_REFERENCE.md)** — Authentication and rate-limiting details.

**Estimated time investment:** Half-day initial review; integrate the annual checklist into your governance cycle.

---

### For Developers Integrating with EIME

You're building a custom dashboard, automation, or report.

1. **[API_REFERENCE.md](./API_REFERENCE.md)** — Endpoints, auth, error codes, webhooks.
2. **[ROLES_AND_PERMISSIONS.md](./ROLES_AND_PERMISSIONS.md)** — Understand role-based scoping.
3. **[SECURITY_BEST_PRACTICES.md](./SECURITY_BEST_PRACTICES.md)** — Webhook signatures and credential handling.
4. **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** — Local dev setup.

---

### For New Vestry / Finance Committee Members

You don't operate EIME but you oversee the people who do.

1. **[FAQ.md](./FAQ.md)** — High-level orientation.
2. **[ROLES_AND_PERMISSIONS.md](./ROLES_AND_PERMISSIONS.md)** — How segregation of duties works.
3. **[OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md)** — Skim the monthly and annual cadence.
4. **[SECURITY_BEST_PRACTICES.md](./SECURITY_BEST_PRACTICES.md)** — Annual security review section.

**Estimated time investment:** 1 hour orientation.

---

## Quick Links by Topic

| I want to... | Go to |
|--------------|-------|
| Install EIME | [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) |
| Connect to Plaid | [PLAID_SETUP.md](./PLAID_SETUP.md) |
| Connect to ACS Realm | [ACS_REALM_SETUP.md](./ACS_REALM_SETUP.md) |
| Configure my church for the first time | [INITIAL_SETUP.md](./INITIAL_SETUP.md) |
| Know my daily routine | [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md) |
| Add a new user | [ROLES_AND_PERMISSIONS.md](./ROLES_AND_PERMISSIONS.md) |
| Fix a posting error | [TROUBLESHOOTING_GUIDE.md](./TROUBLESHOOTING_GUIDE.md) |
| Build an integration | [API_REFERENCE.md](./API_REFERENCE.md) |
| Pass a security audit | [SECURITY_BEST_PRACTICES.md](./SECURITY_BEST_PRACTICES.md) |
| Answer a quick question | [FAQ.md](./FAQ.md) |

---

## Conventions Used in This Documentation

- **Code blocks** indicate exact commands or file contents to type or paste.
- **`monospace`** marks file paths, environment variables, and configuration keys.
- **Bold** highlights actions you should take or key concepts.
- **> Insert screenshot N** placeholders mark where production documentation should embed UI screenshots.
- **ASCII diagrams** show data flow and approval lifecycle.

All documentation cross-references use relative Markdown links so the bundle works whether served from your wiki, GitHub, or local filesystem.

---

## Document Maintenance

When a workflow changes, update the affected document **and** any cross-references in others. Common ripple paths:

- New role added → update `ROLES_AND_PERMISSIONS.md`, `API_REFERENCE.md`, `INITIAL_SETUP.md`
- New approval-chain rule → update `OPERATIONS_MANUAL.md` examples
- ACS UI selector changed → update `ACS_REALM_SETUP.md` Selector Drift section

A monthly read-through by the treasurer keeps the docs current.
