# EIME Security Best Practices

**Audience:** IT security teams and finance compliance officers responsible for governing EIME.

**Goal:** A pragmatic, actionable security baseline that protects credentials, data, and audit trails — and that satisfies typical nonprofit audit and SOX-light expectations.

---

## Table of Contents

1. [Threat Model](#threat-model)
2. [Credential Management](#credential-management)
3. [Access Control (RBAC)](#access-control-rbac)
4. [Audit Trail Integrity](#audit-trail-integrity)
5. [Data Encryption](#data-encryption)
6. [Backup and Restore Security](#backup-and-restore-security)
7. [Incident Response Procedures](#incident-response-procedures)
8. [Compliance Considerations](#compliance-considerations)
9. [Annual Security Review Checklist](#annual-security-review-checklist)

---

## Threat Model

Understanding what you're protecting against shapes every other decision below.

### Assets to Protect

| Asset | Sensitivity | Why |
|-------|-------------|-----|
| Plaid access tokens | Critical | Read access to bank balances and transactions |
| ACS Realm service credentials | Critical | Write access to general ledger |
| Fernet encryption key | Critical | Decrypts all stored credentials |
| Audit trail | Critical | Tamper-evidence depends on chain integrity |
| Invoice PDFs | Sensitive | May contain donor PII, vendor banking info |
| User passwords | Sensitive | Account compromise risk |
| Financial reports | Internal | Disclosure embarrassment, not fraud |

### Likely Attackers

1. **Opportunistic phisher** — emails staff with a fake "EIME password reset" link to steal credentials.
2. **Insider misuse** — staff member with legitimate access uses it outside policy (self-approving payments to themselves).
3. **Vendor-impersonation fraud** — an attacker sends a forged invoice with a bank-account-change request, hoping it slips through.
4. **Lost laptop** — a treasurer's laptop with cached EIME session is stolen.
5. **Ransomware** — opportunistic encryption of the EIME server.

### Out of Scope

EIME is not designed to defend against a sophisticated nation-state actor. If your threat model includes that, additional controls (network microsegmentation, hardware security modules, dedicated SIEM) are required.

---

## Credential Management

### Plaid

- **Plaid Secret** lives only in `.env` and your password vault. Never in git, chat, or wiki.
- **Access tokens** are encrypted at rest with Fernet. They never appear in logs.
- **Rotate the Secret annually** in the Plaid dashboard. Update `.env`, restart EIME, verify, document.
- **On staff turnover**, rotate immediately if the departing person had access.

### ACS Realm

- The service account password lives encrypted in `backend/data/acs_credentials.json`.
- **Never reuse** a personal ACS user as the service account — it conflates audit trails and breaks SoD.
- **Disable MFA** for the service account (with documented business justification) — automation cannot complete MFA.
- **Rotate quarterly** or on any password-policy trigger from your diocese.

### SMTP

- Use an **API key** (e.g., SendGrid) rather than a personal mailbox password.
- The key should be scoped to **send only** (no read or admin access).
- **Rotate** when the SMTP provider recommends or annually, whichever is sooner.

### Anthropic API Key

- Used by EIME for LLM calls in agent reasoning.
- **Rotate** every 90 days; Anthropic's dashboard supports rolling keys without downtime.
- **Set a usage cap** in the Anthropic dashboard to limit blast radius if leaked.

### Fernet Encryption Key

The Fernet key (`EIME_FERNET_KEY` in `.env`) decrypts every stored credential. **It is the single most sensitive secret in EIME.**

- **Generate** with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` once and never regenerate casually.
- **Store** in a Tier-1 password vault (1Password Business, Bitwarden Teams, HashiCorp Vault, AWS Secrets Manager).
- **Rotate** every 2 years or upon suspected exposure. Use the rotation tool:

  ```bash
  uv run python -m backend.tools.rotate_fernet --old <old> --new <new>
  ```

  This re-encrypts all stored blobs with the new key.
- **Never commit** the key, even temporarily. `.env` is gitignored — verify with `git check-ignore .env`.

### Password Vault Hygiene

- Every credential above goes in your password vault.
- Each vault entry includes: rotation date, next-rotation date, who rotated, and a link to the rotation procedure.
- Use **shared vaults** for team credentials, not personal vaults.
- Enable **2FA on the vault itself**. The vault is your last line of defense.

---

## Access Control (RBAC)

### Three Roles, Three Caps

EIME's role model is documented in `ROLES_AND_PERMISSIONS.md`. The security implications:

- **FINANCE_STAFF** — read-only. Compromise impact: confidentiality only.
- **BUDGET_OWNER** — can approve up to their cap. Compromise impact: financial within cap.
- **TREASURER_ADMIN** — full configuration access. Compromise impact: catastrophic.

Treat `TREASURER_ADMIN` accounts like domain-admin accounts. **No more than 3** active TREASURER_ADMIN users in a typical parish; **2** is the SoD-friendly minimum.

### Two-Factor Authentication

Out of the box, EIME uses email + password. For production deployments, **strongly recommend** layering one of:

- TOTP via authenticator app (configurable via `EIME_REQUIRE_TOTP=true`)
- SSO with your diocese's identity provider (SAML/OIDC, available as a paid module)

Make 2FA mandatory for `TREASURER_ADMIN` at minimum.

### Session Management

- Sessions expire after 24 hours of inactivity by default. Lower to 8 hours for `TREASURER_ADMIN`.
- Logout buttons immediately invalidate the server-side session.
- On password change, all existing sessions for that user are invalidated.

### Approval Email Links

Approval emails contain JWT-signed action URLs. Risks:

- Anyone with the email can act. **Train staff** never to forward approval emails.
- URLs expire in 7 days.
- Acting on a link is logged with the original recipient as the actor.

For high-value approvals (over $50K), require login + approval — disable email-button approvals for that threshold via `EIME_EMAIL_APPROVAL_MAX=50000`.

### Network Surface

- The EIME backend should listen only on `127.0.0.1` and be exposed through nginx.
- Restrict the admin IP whitelist via nginx if your deployment serves only on-site users.
- Block all egress except: Plaid API, ACS Realm host, Anthropic API, SMTP provider, Plaid CDN (`cdn.plaid.com`).

---

## Audit Trail Integrity

`backend/audit_trails/audit_log.jsonl` is **append-only and hash-chained**. Each entry contains:

- `prev_hash` — SHA-256 of the previous entry
- `hash` — SHA-256 of the current entry's content + prev_hash

This gives tamper evidence: any modification or deletion of a historical entry breaks the chain on the next verification.

### Verification

Run quarterly:

```bash
uv run python -m backend.tools.verify_audit_chain
```

Expected output: `OK: N entries, chain intact`. Any other output is a P0 incident.

### File-System Protections

```bash
sudo chattr +a /opt/eime/backend/audit_trails/audit_log.jsonl   # Linux: append-only flag
```

On filesystems that support it, this prevents even root from rewriting the file (only appending). Combine with off-host streaming for full protection.

### Off-Host Streaming

For maximum integrity, stream the audit log to an immutable destination as it's written:

- AWS S3 with object-lock and write-once
- An on-premise WORM appliance
- A SIEM with retention guarantees

Configure in `.env`:

```bash
EIME_AUDIT_FORWARD=s3://your-bucket/eime-audit/
EIME_AUDIT_FORWARD_INTERVAL=60
```

If the local copy is ever tampered with, the off-host copy reveals the truth.

---

## Data Encryption

### At Rest

- Plaid access tokens, ACS Realm passwords: Fernet (AES-128 in CBC mode + HMAC-SHA256).
- Database (if PostgreSQL): enable Transparent Data Encryption (TDE) or column-level encryption for `users.password_hash`.
- File-system: full-disk encryption (LUKS on Linux) is recommended for the EIME host.

### In Transit

- All HTTP must be HTTPS. Set up TLS via nginx + Let's Encrypt (see `DEPLOYMENT_GUIDE.md`).
- Plaid, Anthropic, ACS Realm calls are HTTPS by default.
- SMTP: enforce STARTTLS (`SMTP_USE_TLS=true`).
- Internal: backend listens on `127.0.0.1` only; nginx terminates TLS and forwards over loopback.

### Password Hashing

User passwords are stored as Argon2 hashes (cost: t=2, m=64MiB, p=4). To verify:

```python
import argon2
argon2.PasswordHasher().verify(stored_hash, plaintext)
```

Never store, log, or transmit plaintext passwords.

### Key Lifecycle

| Key | Lifetime | Rotation Tooling |
|-----|----------|------------------|
| TLS certificate | 90 days (Let's Encrypt) | Auto-renewed by certbot |
| Fernet key | 2 years | `backend.tools.rotate_fernet` |
| Plaid Secret | 1 year | Plaid dashboard + restart |
| ACS service password | 90 days | Manual ACS UI + EIME settings |
| Anthropic key | 90 days | Anthropic dashboard + `.env` |
| User passwords | 180 days | EIME password reset flow |

---

## Backup and Restore Security

### Backup Targets

Production backups must include:

- `backend/data/`
- `backend/audit_trails/`
- `backend/audit_pdfs/`
- `backend/uploads/`
- `.env` (including Fernet key — back this up to your password vault, not your file backup)

### Backup Encryption

If your backup destination is not already encrypted:

```bash
tar czf - -C /opt/eime/backend data audit_trails | gpg -c --cipher-algo AES256 > /var/backups/eime/$(date +%F).tar.gz.gpg
```

Use a backup-specific GPG key, stored in your password vault (not on the EIME host).

### Restore Procedures

Restore drills are mandatory. Once a quarter:

1. Spin up a clean test VM.
2. Install EIME from scratch.
3. Restore the latest backup.
4. Verify the audit chain is intact.
5. Confirm Plaid and ACS connections work with restored credentials.
6. Document the drill (date, who performed, RTO achieved).

A backup that hasn't been restored is a wish. The first time you restore, in a real incident, is the worst time to discover the backup is broken.

### Backup Retention

- **Daily incrementals** for 30 days
- **Weekly fulls** for 90 days
- **Monthly fulls** for 7 years (matches audit trail retention)
- **Off-site copy** at all retention tiers

---

## Incident Response Procedures

### Severity Levels

| Severity | Examples | Response Time |
|----------|----------|---------------|
| P0 | Audit chain broken; Fernet key leaked; treasurer credentials compromised | Immediate (page treasurer + IT lead) |
| P1 | Plaid Secret leaked; suspicious posting attempt; large unauthorized JE | < 1 hour |
| P2 | User credential compromised; phishing reported | < 4 hours |
| P3 | Vendor-impersonation invoice caught by EIME | Next business day |

### General Playbook

1. **Contain.**
   - Disable affected user accounts.
   - Rotate any potentially exposed credentials immediately.
   - For P0: take EIME offline (`sudo systemctl stop eime`) until contained.
2. **Preserve evidence.**
   - Snapshot the audit trail as of detection time.
   - Snapshot system logs.
   - Note the timeline (who noticed, when, how).
3. **Investigate.**
   - Use the audit trail to identify the scope (which actions, by whom, on which resources).
   - Check for downstream actions (did unauthorized JEs post to ACS? Were payments released?).
4. **Remediate.**
   - Reverse unauthorized JEs in ACS (cannot be deleted; must be offsetting JEs).
   - Reach out to vendors if payments were misdirected.
   - Update controls to prevent recurrence.
5. **Document.**
   - Incident report covering: detection, timeline, scope, actions taken, root cause, prevention.
   - File with the audit packet.
6. **Notify.**
   - Rector / vestry within 24 hours of P0 or P1.
   - Diocese for material events.
   - Donors if their PII was exposed (per state breach-notification laws).

### Specific Playbooks

#### Fernet Key Leaked

1. Take EIME offline.
2. Generate a new Fernet key.
3. Run `rotate_fernet` to re-encrypt all stored credentials (you need the old key to decrypt before re-encrypting).
4. **Rotate every credential** EIME ever knew (Plaid Secret, ACS password, Anthropic key, SMTP key, all user passwords) — assume the attacker has them.
5. Bring EIME back online with the new key.
6. Audit-trail review for any malicious actions during the exposure window.

#### Audit Chain Broken

1. **Do not modify the file** further.
2. Snapshot the file immediately.
3. Compare the snapshot to your off-host copy — the divergence point identifies the tampering.
4. Restore from the off-host copy if it's intact.
5. Treat as a confirmed insider attack until proven otherwise.

#### Plaid Access Token Compromised

1. Revoke the token via Plaid dashboard (`Items → Revoke`).
2. Re-link affected accounts via Plaid Link (creates new tokens).
3. Review recent `plaid.balance.read` audit events for unauthorized access.
4. Confirm no payment fraud occurred (compare to expected outflows).

---

## Compliance Considerations

### SOX (for nonprofits with revenues > $X — consult legal)

EIME satisfies the spirit of SOX-style internal controls:

- **Segregation of duties** via three-role RBAC
- **Audit trail** with tamper evidence
- **Change management** via configuration history
- **Access reviews** via quarterly user-access review

### GAAP

- EIME's JEs follow standard double-entry: every JE balances; debits and credits per fund.
- Period-close locking prevents post-hoc modification of closed periods.
- Restricted-fund tracking enforces ASC 958 compliance.

### FASB ASC 958 (Nonprofit-Specific)

- Restricted fund balances tracked separately.
- Releases from restriction documented per donor intent.
- Statement of Activities and Statement of Functional Expenses generated from EIME's GL.

### IRS Form 990

- EIME's reports feed Form 990 schedules:
  - Schedule A (program services)
  - Schedule G (fundraising activities)
  - Schedule M (non-cash contributions)
- 1099-NEC generation with W-9 tracking.

### State Charitable Solicitation Registration

- Donor PII handling: encrypted at rest, transmitted only over HTTPS, retained per your registration requirements.

### PCI DSS

- EIME does **not** store credit card data. If you accept cards, your card processor handles PCI scope.
- Confirm no cardholder data appears in invoice PDFs (they shouldn't — but if a vendor includes a card number on a receipt, redact before upload).

### Data Subject Rights

If any individual (donor, vendor, employee) requests a copy of their data:

```bash
uv run python -m backend.tools.data_subject_export --subject "vendor@example.com"
```

This produces a JSON bundle of all references to that subject across invoices, JEs, payments, and audit entries. Useful for GDPR-like requests, even though most U.S. nonprofits aren't legally subject to GDPR.

---

## Annual Security Review Checklist

Run every January as part of year-end. Sign off and file with the audit packet.

- [ ] Verify audit chain across full prior year (`verify_audit_chain --since 2025-01-01`)
- [ ] Rotate all credentials past their interval
- [ ] Rotate Fernet key (if 2 years elapsed)
- [ ] Confirm all `TREASURER_ADMIN` users are still authorized; disable any departed
- [ ] Review authority matrix for any changes in policy
- [ ] Review approval-chain emails for any departed staff
- [ ] Confirm 2FA enrollment for all admins
- [ ] Test restore from a recent backup in a sandbox
- [ ] Review off-host audit-log copies for completeness
- [ ] Confirm SSL certificate is valid and auto-renews
- [ ] Penetration test by an independent party (every 2 years)
- [ ] Review incident log; confirm all incidents are closed
- [ ] Confirm SOX/GAAP/ASC 958 controls in `ROLES_AND_PERMISSIONS.md` reflect current bylaws
- [ ] Update threat model if church operations changed materially
- [ ] Brief vestry / finance committee on review outcomes

---

## Cross-References

- Roles and SoD: `ROLES_AND_PERMISSIONS.md`
- Audit-trail mechanics: `OPERATIONS_MANUAL.md`
- Deployment hardening: `DEPLOYMENT_GUIDE.md`
- Plaid security details: `PLAID_SETUP.md`
- ACS security details: `ACS_REALM_SETUP.md`
- Incident-related troubleshooting: `TROUBLESHOOTING_GUIDE.md`
