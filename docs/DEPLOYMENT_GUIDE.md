# EIME Deployment Guide

**Audience:** IT and DevOps teams responsible for deploying and operating the Embark Invoice Mapping Engine (EIME).

**Goal:** A repeatable, secure, production-ready deployment of the EIME backend and frontend, with the supporting integrations (Plaid, ACS Realm, SMTP) wired in.

---

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Installation Steps](#installation-steps)
3. [Environment Configuration](#environment-configuration)
4. [Database and Data Layout](#database-and-data-layout)
5. [Dependency Installation](#dependency-installation)
6. [Running the Application](#running-the-application)
7. [SSL/TLS Setup for Production](#ssltls-setup-for-production)
8. [Docker Deployment](#docker-deployment)
9. [Health Check Endpoints](#health-check-endpoints)
10. [Backup and Restore Procedures](#backup-and-restore-procedures)
11. [Troubleshooting Common Installation Issues](#troubleshooting-common-installation-issues)

---

## System Requirements

EIME runs on a single host for small/medium parishes and dioceses. For larger deployments (multi-site dioceses, > 5,000 invoices/month), see the scaling notes at the bottom of this section.

### Minimum (Development / Pilot)

| Component | Requirement |
|-----------|-------------|
| OS | Linux (Ubuntu 22.04 LTS or Debian 12), macOS 13+, or Windows 11 with WSL2 |
| Python | 3.11 or 3.12 (3.10 is not supported per `pyproject.toml`) |
| RAM | 4 GB |
| Disk | 10 GB free (for data, audit trails, embeddings cache) |
| CPU | 2 vCPU |
| Network | Outbound HTTPS to api.plaid.com, ACS Realm hosts, Anthropic API |

### Recommended (Production)

| Component | Requirement |
|-----------|-------------|
| OS | Ubuntu 22.04 LTS |
| Python | 3.11.x |
| RAM | 8 GB (16 GB if running OCR-heavy invoice volumes) |
| Disk | 50 GB SSD (audit trails are append-only and grow over time) |
| CPU | 4 vCPU |
| Reverse proxy | nginx or Caddy |
| TLS | Valid certificate (Let's Encrypt or organizational CA) |

### System Dependencies

EIME uses several third-party tools that must be installed at the OS level before `uv sync`:

- **tesseract-ocr** — required by `pytesseract` for invoice OCR fallback when PDFs lack a text layer.
- **poppler-utils** — required by `pdfplumber` and `pypdf` for image-based PDFs.
- **Node.js 20+** — required by Playwright (for ACS Realm browser automation) and the frontend.
- **libffi-dev**, **libssl-dev**, **build-essential** — required for native Python wheels (cryptography, chromadb).

Install on Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y \
  tesseract-ocr \
  poppler-utils \
  libffi-dev libssl-dev build-essential \
  curl ca-certificates
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs
```

Install on macOS (Homebrew):

```bash
brew install tesseract poppler node@20
```

### Database

EIME uses **JSON files on disk** for its operational data store by default (see [Database and Data Layout](#database-and-data-layout)). PostgreSQL is **optional** and only required if you enable cross-session coordination (multi-treasurer setups). For most single-parish deployments, JSON-on-disk is sufficient.

---

## Installation Steps

### 1. Clone the Repository

```bash
sudo mkdir -p /opt/eime
sudo chown $USER:$USER /opt/eime
cd /opt/eime
git clone <your-repo-url> .
```

### 2. Install `uv` (Python Package Manager)

EIME uses [`uv`](https://github.com/astral-sh/uv) for fast, reproducible dependency installation.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
uv --version
```

### 3. Sync Python Dependencies

From the project root:

```bash
uv sync
```

This reads `pyproject.toml` and `uv.lock` and creates a `.venv/` directory with all pinned dependencies. It is idempotent — re-run it any time `pyproject.toml` changes.

### 4. Install Playwright Browsers

ACS Realm posting uses Playwright to automate the ACS web UI. Install browser binaries:

```bash
uv run playwright install chromium
uv run playwright install-deps chromium  # Linux only
```

### 5. Install Frontend Dependencies

```bash
cd frontend
npm install
npm run build       # builds production assets to frontend/dist/
cd ..
```

### 6. Create Required Directories

```bash
mkdir -p backend/data backend/audit_trails backend/audit_pdfs backend/uploads
mkdir -p backend/data/chroma  # vector store
chmod 750 backend/data backend/audit_trails
```

---

## Environment Configuration

EIME is configured through a `.env` file at the project root. Copy the template and fill in real values:

```bash
cp .env.example .env
chmod 600 .env  # protect secrets
```

### Required Variables

```bash
# === Anthropic (LLM) ===
ANTHROPIC_API_KEY=sk-ant-...

# === Plaid ===
PLAID_CLIENT_ID=your_plaid_client_id
PLAID_SECRET=your_plaid_secret
PLAID_ENV=sandbox        # sandbox | development | production
PLAID_PRODUCTS=auth,transactions
PLAID_COUNTRY_CODES=US

# === ACS Realm ===
ACS_REALM_BASE_URL=https://realm.acstechnologies.com
ACS_REALM_USERNAME=treasurer@yourchurch.org
ACS_REALM_PASSWORD=...
ACS_HEADLESS=true        # false to watch automation in a real browser

# === SMTP (approval emails) ===
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USERNAME=apikey
SMTP_PASSWORD=...
SMTP_FROM_ADDRESS=eime@yourchurch.org

# === Encryption ===
EIME_FERNET_KEY=         # 44-char base64 key; generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# === Server ===
EIME_HOST=0.0.0.0
EIME_PORT=8000
EIME_LOG_LEVEL=INFO

# === Optional: PostgreSQL ===
# DATABASE_URL=postgresql://eime:password@localhost:5432/eime
```

### Generating the Fernet Key

The Fernet key encrypts sensitive fields (Plaid access tokens, ACS passwords) at rest. **Generate it once and never commit it to git.**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the value in `.env` and back it up to your password manager. **If you lose this key you will not be able to decrypt stored credentials and must re-link Plaid and re-enter ACS passwords.**

---

## Database and Data Layout

EIME persists state under `backend/data/`. The default JSON-file layout:

```
backend/
  data/
    chart_of_accounts.json          # COA per church
    budget.json                     # annual budget snapshot
    approval_chains.json            # GL pattern -> approver email
    budgetary_authority.json        # role+GL -> amount limit
    plaid_items.json                # encrypted Plaid access tokens
    acs_credentials.json            # encrypted ACS Realm credentials
    invoices/                       # one JSON per ingested invoice
    journal_entries/                # one JSON per JE
    payments/                       # payment status records
    chroma/                         # vector embeddings (Chroma DB files)
  audit_trails/
    audit_log.jsonl                 # append-only hash-chained audit events
  audit_pdfs/                       # signed PDF receipts per posted JE
  uploads/                          # raw uploaded invoice PDFs
```

### Initial Data Bootstrap

On first run, EIME will create empty JSON files. To pre-load a chart of accounts, drop a file at `backend/data/chart_of_accounts.json` matching the schema documented in `INITIAL_SETUP.md`.

### Permissions

Restrict the data directories to the EIME service user:

```bash
sudo useradd -r -s /bin/false eime
sudo chown -R eime:eime backend/data backend/audit_trails backend/audit_pdfs
sudo chmod 750 backend/data backend/audit_trails backend/audit_pdfs
sudo chmod 640 backend/data/*.json
```

---

## Dependency Installation

The full Python dependency surface is declared in `pyproject.toml`. Key groups:

| Group | Purpose |
|-------|---------|
| `fastapi`, `uvicorn` | HTTP server |
| `pydantic` | Data validation |
| `crewai` | Multi-agent orchestration |
| `chromadb`, `sentence-transformers` | GL classification semantic search |
| `pypdf`, `pdfplumber`, `pytesseract`, `Pillow` | Invoice ingestion / OCR |
| `anthropic` | Claude LLM client |
| `plaid-python` | Plaid SDK |
| `cryptography` | Fernet encryption for credentials |
| `apscheduler`, `croniter` | Scheduled jobs (balance refresh, reconciliation) |
| `openpyxl`, `pandas` | Budget import, variance reports |

### Optional Dependencies

- **Playwright** is installed via `uv run playwright install`. Without it, ACS posting will fail with `PlaywrightNotInstalledError`.
- **PostgreSQL driver (`psycopg2-binary`)** is only required if you set `DATABASE_URL`. Install with `uv add psycopg2-binary`.

Verify installation:

```bash
uv run python -c "import fastapi, plaid, chromadb, anthropic; print('OK')"
uv run playwright --version
```

---

## Running the Application

### Development Mode

From the project root:

```bash
./start.sh
```

This script (provided in the repo) launches:
- Backend: `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
- Frontend dev server: `npm run dev` in `frontend/` (typically on port 5173)

### Production Mode

Use a process supervisor. Example **systemd** unit at `/etc/systemd/system/eime.service`:

```ini
[Unit]
Description=EIME Backend
After=network.target

[Service]
Type=simple
User=eime
WorkingDirectory=/opt/eime
EnvironmentFile=/opt/eime/.env
ExecStart=/opt/eime/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now eime
sudo systemctl status eime
```

The frontend in production should be served as static files by nginx (see SSL section below) — not via the dev server.

---

## SSL/TLS Setup for Production

EIME must be served over HTTPS in production. Plaid Link and SMTP relays will reject plain-HTTP origins.

### nginx + Let's Encrypt

Install:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/eime`:

```nginx
server {
    listen 80;
    server_name eime.yourchurch.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name eime.yourchurch.org;

    ssl_certificate /etc/letsencrypt/live/eime.yourchurch.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/eime.yourchurch.org/privkey.pem;

    # Frontend static files
    root /opt/eime/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;     # JE posting can take a while
    }
}
```

Enable site and obtain certificate:

```bash
sudo ln -s /etc/nginx/sites-available/eime /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d eime.yourchurch.org
```

Certbot installs a renewal cron automatically. Verify with `sudo certbot renew --dry-run`.

---

## Docker Deployment

A Dockerfile is **not** shipped by default, but a minimal one looks like:

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr poppler-utils \
    libffi-dev libssl-dev build-essential \
    curl && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
RUN uv run playwright install --with-deps chromium

COPY backend ./backend
COPY .env ./.env

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t eime:latest .
docker run -d \
  --name eime \
  -p 8000:8000 \
  -v /opt/eime/data:/app/backend/data \
  -v /opt/eime/audit_trails:/app/backend/audit_trails \
  --env-file .env \
  eime:latest
```

Mount volumes for `data/`, `audit_trails/`, and `audit_pdfs/` so they survive container rebuilds.

---

## Health Check Endpoints

EIME exposes the following endpoints for monitoring:

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Returns `{"status":"ok"}` if the API is responsive |
| `GET /health/plaid` | Verifies Plaid client can reach `api.plaid.com` |
| `GET /health/acs` | Tests ACS Realm login (uses cached cookie) |
| `GET /health/db` | Confirms data directory is readable/writable |

Configure your monitoring (Prometheus blackbox, Pingdom, UptimeRobot) to poll `/health` every minute. Alert on three consecutive failures.

---

## Backup and Restore Procedures

EIME state is **file-based** which makes backup straightforward.

### What to Back Up

| Path | Frequency | Retention |
|------|-----------|-----------|
| `backend/data/` | Daily | 90 days |
| `backend/audit_trails/` | Hourly | 7 years (compliance) |
| `backend/audit_pdfs/` | Daily | 7 years (compliance) |
| `.env` | On change | Forever (secure vault) |

### Backup Script

```bash
#!/bin/bash
# /opt/eime/scripts/backup.sh
TS=$(date +%Y%m%d-%H%M%S)
DEST=/var/backups/eime/$TS
mkdir -p $DEST
tar czf $DEST/data.tar.gz -C /opt/eime/backend data
tar czf $DEST/audit.tar.gz -C /opt/eime/backend audit_trails audit_pdfs
find /var/backups/eime -mtime +90 -delete
```

Schedule via cron:

```
0 2 * * * /opt/eime/scripts/backup.sh
```

### Restore

```bash
sudo systemctl stop eime
tar xzf /var/backups/eime/<TS>/data.tar.gz -C /opt/eime/backend
tar xzf /var/backups/eime/<TS>/audit.tar.gz -C /opt/eime/backend
sudo systemctl start eime
```

**Audit trails are hash-chained.** A successful restore must include the entire `audit_log.jsonl` — partial restoration breaks the chain and will fail audit verification.

---

## Troubleshooting Common Installation Issues

### `uv sync` fails on cryptography wheel

You are missing build tools. Install `libffi-dev`, `libssl-dev`, `build-essential` (Linux) or Xcode CLI tools (macOS).

### `pytesseract.TesseractNotFoundError`

`tesseract` is not on PATH. Install via apt/brew (see [System Dependencies](#system-dependencies)) and verify with `tesseract --version`.

### `playwright._impl._errors.Error: Executable doesn't exist`

You ran `playwright install` but not `playwright install-deps`. On Linux:

```bash
uv run playwright install-deps chromium
```

### `chromadb` fails to load embeddings

ChromaDB downloads a sentence-transformer model on first use. Ensure outbound HTTPS to `huggingface.co` is allowed, or pre-cache the model:

```bash
uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### Frontend build fails with `ERR_OSSL_EVP_UNSUPPORTED`

Node 17+ deprecated some OpenSSL primitives used by older webpack. Use Node 20 LTS as recommended above.

### Plaid returns `INVALID_API_KEYS`

Your `PLAID_ENV` does not match the credentials. Sandbox secret cannot be used against production endpoints. See `PLAID_SETUP.md`.

### ACS login times out

ACS occasionally throttles automation. Try `ACS_HEADLESS=false` to watch the browser; you may need to update selectors if ACS changed its UI (see `ACS_REALM_SETUP.md`).

---

## Cross-References

- Plaid setup details: `PLAID_SETUP.md`
- ACS Realm setup: `ACS_REALM_SETUP.md`
- First-day configuration for finance staff: `INITIAL_SETUP.md`
- Security hardening: `SECURITY_BEST_PRACTICES.md`
- Day-2 operations: `OPERATIONS_MANUAL.md`
