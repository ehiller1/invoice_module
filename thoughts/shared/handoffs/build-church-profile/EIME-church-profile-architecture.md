# EIME Church Profile Architecture — Build Handoff
Updated: 2026-05-06T00:00:00Z
Project: /Users/erichillerbrand/chart of accounts

---

## Goal

Enable the next implementation phase to confidently design and build the church profile
system — covering how churches are created, how their Charts of Accounts and funds are
managed, and how denomination-specific rules are applied at runtime.

---

## Architecture Overview

EIME (Embark Invoice Mapping Engine) is a FastAPI + CrewAI multi-agent system that
processes church invoices and maps them to a church-specific Chart of Accounts (COA).

The system has two distinct runtime concerns:

1. **Church profile management** — CRUD operations on a church's accounting context
   (accounts, funds, denomination, fiscal year). Fully synchronous REST.

2. **Invoice processing pipeline** — Async pipeline (extract → classify → denomination
   rules → GL map → review → HITL → journal entry) triggered per PDF upload.

Church data is stored as **flat JSON files**, one per church, with a **ChromaDB
vector index** rebuilt on every mutation for semantic account search.

There is no SQL database. No migrations. No ORM.

---

## Key Files and Their Purposes

### Entry Points

| File | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app, all REST endpoints, startup hook |
| `backend/flow.py` | Async invoice pipeline orchestrator |
| `start.sh` | Dev server launcher (`uvicorn backend.main:app --reload`) |

### Models

| File | Purpose |
|------|---------|
| `backend/models/schemas.py` | All Pydantic models: `AccountingContext`, `Account`, `Fund`, `DenominationType`, enums |

### Persistence

| File | Purpose |
|------|---------|
| `backend/tools/coa_store.py` | Read/write church JSON files; rebuild ChromaDB index |
| `backend/data/context_<church_id>.json` | Per-church AccountingContext on disk |
| `backend/data/chroma/` | ChromaDB persistent store (SQLite-backed) |

### Processing Tools (invoked by pipeline)

| File | Purpose |
|------|---------|
| `backend/tools/denomination_rules.py` | Keyword-based denomination overrides applied post-classification |
| `backend/tools/classifier.py` | Line-item classifier using taxonomy keywords |
| `backend/tools/gl_mapper.py` | Maps classified items to GL account numbers |
| `backend/tools/pdf_extractor.py` | PDF text extraction |
| `backend/tools/journal_builder.py` | Constructs journal entries |
| `backend/tools/reviewer.py` | Allocation review |
| `backend/tools/risk_assessor.py` | Risk scoring |
| `backend/tools/fraud_detector.py` | Fraud detection |
| `backend/tools/chat_router.py` | Conversational Q&A routing |
| `backend/tools/spreadsheet_parser.py` | Excel/CSV COA import |

### Skill Registry

| Path | Purpose |
|------|---------|
| `backend/tools/skill_registry.py` | Scans `backend/skills/` for SKILL.md files; lazy-loads bodies |
| `backend/agents/crews.py` | CrewAI agent factories (orchestrator, researcher, worker, reviewer) |

### Skills (SKILL.md files)

Skills are markdown files with YAML frontmatter. They provide domain expertise to
CrewAI agents at runtime. The registry scans them on startup.

```
backend/skills/
  orchestrator/invoice_processing_workflow/SKILL.md
  researcher/coa_reference_loader/SKILL.md
  researcher/vendor_history_lookup/SKILL.md
  worker/denomination_umc/SKILL.md
  worker/denomination_episcopal/SKILL.md
  worker/denomination_presbyterian/SKILL.md
  worker/denomination_baptist/SKILL.md
  worker/denomination_catholic_parish/SKILL.md
  worker/line_item_classifier/SKILL.md
  worker/gl_account_mapper/SKILL.md
  worker/expense_taxonomy_v1/SKILL.md
  worker/journal_entry_builder/SKILL.md
  worker/pdf_extraction/SKILL.md
  reviewer/allocation_reviewer/SKILL.md
  reviewer/fraud_detector/SKILL.md
  reviewer/risk_assessor/SKILL.md
  conversation/hitl_invoice_gate/SKILL.md
  conversationalist/agent_qa_interface/SKILL.md
  membrane/accounting_domain_distillation/SKILL.md
```

### Frontend

| File | Purpose |
|------|---------|
| `frontend/index.html` | Dashboard / upload UI |
| `frontend/coa.html` | COA / account browser UI |
| `frontend/jobs.html` | Job status UI |
| `frontend/chat.html` | Agent Q&A chat |
| `frontend/skills.html` | Skill registry viewer |

---

## Church Profile Data Model

### AccountingContext (the central church object)

Defined in `backend/models/schemas.py` at line 195.

```python
class AccountingContext(BaseModel):
    church_id: str                          # slug, e.g. "grace_umc"
    church_name: str                        # display name
    denomination_type: DenominationType     # enum (see below)
    fiscal_year: int                        # e.g. 2026
    fiscal_year_start: date                 # e.g. date(2026, 1, 1)
    accounts: List[Account]
    funds: List[Fund]
    allocation_schedules: List[AllocationSchedule]
    capitalisation_threshold_usd: Decimal   # default 2500
    parsonage_allowance_current_year: Decimal
    parsonage_allowance_used_ytd: Decimal
    apportionment_accounts: List[ApportionmentAccount]
    warnings: List[str]
```

### Account

```python
class Account(BaseModel):
    account_number: str        # "1010", "5100", etc.
    account_name: str
    account_type: str          # "Asset" | "Liability" | "Equity" | "Revenue" | "Expense"
    fund_id: str               # foreign key into funds list
    restriction_class: RestrictionClass
    active: bool = True
```

### Fund

```python
class Fund(BaseModel):
    fund_id: str               # "GEN", "BLDG", "MISS", etc.
    fund_name: str
    restriction_class: RestrictionClass
    fund_category: FundCategory
    purpose_description: Optional[str]
    expenditure_rules: Optional[str]
    current_balance: Decimal
```

### Key Enums

```python
class DenominationType(str, Enum):
    EPISCOPAL = "EPISCOPAL"
    UMC = "UMC"
    PRESBYTERIAN_PCUSA = "PRESBYTERIAN_PCUSA"
    BAPTIST_INDEPENDENT = "BAPTIST_INDEPENDENT"
    CATHOLIC_PARISH = "CATHOLIC_PARISH"
    NONDENOMINATIONAL = "NONDENOMINATIONAL"
    AOG = "AOG"
    OTHER = "OTHER"

class RestrictionClass(str, Enum):
    WITHOUT_RESTRICTION = "WITHOUT_RESTRICTION"
    WITH_RESTRICTION_PURPOSE = "WITH_RESTRICTION_PURPOSE"
    WITH_RESTRICTION_PERMANENT = "WITH_RESTRICTION_PERMANENT"

class FundCategory(str, Enum):
    GENERAL_OPERATING = "GENERAL_OPERATING"
    TEMP_RESTRICTED_PURPOSE = "TEMP_RESTRICTED_PURPOSE"
    TEMP_RESTRICTED_TIME = "TEMP_RESTRICTED_TIME"
    PERMANENTLY_RESTRICTED = "PERMANENTLY_RESTRICTED"
    BOARD_DESIGNATED = "BOARD_DESIGNATED"
    CAPITAL_CAMPAIGN = "CAPITAL_CAMPAIGN"
```

---

## Database / Persistence

**There is no SQL database.** Church data is stored as flat JSON files.

### Storage Layout

```
backend/data/
  context_grace_umc.json          # one file per church
  context_test_presbyterian.json
  chroma/
    chroma.sqlite3                # ChromaDB stores embeddings here
```

### File naming convention

`context_{church_id}.json` where `church_id` is a slug (lowercase, underscores).

### How persistence works (coa_store.py)

- `save_accounting_context(ctx)` — serializes `AccountingContext` to JSON, then calls
  `_rebuild_index(ctx)` to refresh ChromaDB.
- `load_accounting_context(church_id)` — reads JSON file, validates with Pydantic.
- `list_churches()` — globs `context_*.json` and reads minimal metadata from each.
- ChromaDB collection name per church: `coa_{church_id}`
- Embedding model: `all-MiniLM-L6-v2` (sentence-transformers, local, no API key needed)

### Job store

Invoice processing jobs (`ProcessingJob`) are stored **in-memory only** in a dict in
`backend/flow.py`. Jobs are lost on server restart. The comment in flow.py notes this
should be replaced with Redis/DB for production.

---

## API Endpoints for Church Management

All endpoints defined in `backend/main.py`. Base path: `http://localhost:8000`

### Church CRUD

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/churches` | List all churches (id, name, denomination, account/fund counts) |
| POST | `/api/churches` | Create church with minimal 6-account COA skeleton |
| GET | `/api/churches/{church_id}/context` | Full AccountingContext JSON |
| GET | `/api/churches/{church_id}/accounts` | Account list |
| GET | `/api/churches/{church_id}/funds` | Fund list |
| POST | `/api/churches/{church_id}/accounts` | Upsert a single account |
| DELETE | `/api/churches/{church_id}/accounts/{account_number}` | Delete account |
| POST | `/api/churches/{church_id}/funds` | Upsert a single fund |
| DELETE | `/api/churches/{church_id}/funds/{fund_id}` | Delete fund |
| POST | `/api/churches/{church_id}/coa/import` | Bulk JSON import (replace or merge) |
| POST | `/api/churches/{church_id}/coa/import-spreadsheet` | Bulk Excel/CSV import |
| GET | `/api/churches/{church_id}/search?q=...&k=5` | Semantic account search |

### POST /api/churches — Create Church Request Body

```json
{
  "church_id": "st_marks_episcopal",
  "church_name": "St. Mark's Episcopal Church",
  "denomination_type": "EPISCOPAL",
  "fiscal_year": 2026
}
```

The endpoint creates a minimal 6-account skeleton:
- 1000 Cash — Checking (Asset, GEN, WITHOUT_RESTRICTION)
- 2010 Accounts Payable (Liability, GEN, WITHOUT_RESTRICTION)
- 4000 Tithes & Offerings (Revenue, GEN, WITHOUT_RESTRICTION)
- 5000 Clergy Compensation (Expense, GEN, WITHOUT_RESTRICTION)
- 7000 Facilities (Expense, GEN, WITHOUT_RESTRICTION)
- 8000 Administration (Expense, GEN, WITHOUT_RESTRICTION)

Plus one fund: GEN — General Operating Fund.

The full COA is then populated via `POST /api/churches/{id}/coa/import` or the
spreadsheet import endpoint.

### Denomination info

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/denominations` | List all supported denominations + skill load status |

---

## Pattern for Adding a New Church

### Step 1: Create the church record

```bash
curl -X POST http://localhost:8000/api/churches \
  -H "Content-Type: application/json" \
  -d '{
    "church_id": "calvary_baptist",
    "church_name": "Calvary Baptist Church",
    "denomination_type": "BAPTIST_INDEPENDENT",
    "fiscal_year": 2026
  }'
```

This creates `backend/data/context_calvary_baptist.json` and seeds the ChromaDB index.

### Step 2: Import the full Chart of Accounts

Option A — JSON bulk import:

```bash
curl -X POST http://localhost:8000/api/churches/calvary_baptist/coa/import \
  -H "Content-Type: application/json" \
  -d '{
    "accounts": [
      {"account_number": "1010", "account_name": "Operating Cash",
       "account_type": "Asset", "fund_id": "GEN",
       "restriction_class": "WITHOUT_RESTRICTION"},
      ...
    ],
    "funds": [
      {"fund_id": "GEN", "fund_name": "General Operating Fund",
       "restriction_class": "WITHOUT_RESTRICTION",
       "fund_category": "GENERAL_OPERATING"}
    ]
  }'
```

Option B — Spreadsheet upload (Excel or CSV):

```bash
curl -X POST http://localhost:8000/api/churches/calvary_baptist/coa/import-spreadsheet \
  -F "file=@calvary_coa.xlsx"
```

### Step 3: Verify

```bash
curl http://localhost:8000/api/churches/calvary_baptist/context
curl http://localhost:8000/api/churches/calvary_baptist/search?q=apportionment
```

### Step 4: Upload an invoice

```bash
curl -X POST http://localhost:8000/api/invoice/upload \
  -F "church_id=calvary_baptist" \
  -F "document_type=INVOICE" \
  -F "file=@invoice.pdf"
```

---

## Denomination-Specific Configuration

Denomination rules are implemented in **two layers** that both activate during invoice
processing:

### Layer 1: Keyword overrides (denomination_rules.py)

Location: `backend/tools/denomination_rules.py`

Contains static keyword-to-category mapping dicts for each denomination:
- `_UMC_OVERRIDES` — apportionments, Wespath, Special Sundays, SECA
- `_EPISCOPAL_OVERRIDES` — diocesan assessment, CPG pension, discretionary fund
- `_CATHOLIC_OVERRIDES` — cathedraticum, Peter's Pence, mass stipends, school subsidy
- `_BAPTIST_OVERRIDES` — Cooperative Program, Lottie Moon, Guidestone, deacon fund
- `_PRESBYTERIAN_OVERRIDES` — per capita, Board of Pensions, One Great Hour

These are applied in `flow.py` at pipeline Step 3b (post-classification, pre-GL-map).

The function `apply_denomination_rules(classified, ctx)` takes the list of classified
line items and the church's AccountingContext, looks up the denomination from `ctx`,
and applies keyword matching to override `expense_category` and inject GL account hints.

### Layer 2: SKILL.md files (agent domain knowledge)

Location: `backend/skills/worker/denomination_*/SKILL.md`

Each file contains deep accounting guidance loaded by CrewAI agents:

| Denomination | Skill File | Key Coverage |
|-------------|-----------|-------------|
| UMC | `denomination_umc/SKILL.md` | Apportionment tables, Wespath benefits, SECA, Special Sundays |
| Episcopal | `denomination_episcopal/SKILL.md` | Diocesan fair share, CPF pension (18%), rectory, endowment |
| Presbyterian PCUSA | `denomination_presbyterian/SKILL.md` | Per capita (GA/Synod/Presbytery), BOP, Terms of Call |
| Baptist | `denomination_baptist/SKILL.md` | Cooperative Program, Lottie Moon, Guidestone, deacon fund |
| Catholic | `denomination_catholic_parish/SKILL.md` | Cathedraticum, USCCB, mass stipends, school subsidy |

Adding a new denomination requires changes in three places:
1. Add to `DenominationType` enum in `backend/models/schemas.py`
2. Add override dict to `backend/tools/denomination_rules.py` and register in `_DENOM_MAP`
3. Create `backend/skills/worker/denomination_<name>/SKILL.md` with frontmatter

### Account Number Conventions (observed from seed data)

| Range | Type | Examples |
|-------|------|---------|
| 1000–1999 | Asset | Cash, investments, land, equipment |
| 2000–2999 | Liability / Pass-through | AP, payroll liabilities, designated gift liabilities |
| 3000–3999 | Net Assets / Equity | Without restriction, purpose restricted, endowment |
| 4000–4999 | Revenue | Tithes, designated gifts by fund |
| 5000–5999 | Personnel Expense | Clergy comp, housing, SECA, lay wages, benefits |
| 6000–6999 | Ministry Expense | Worship, children, youth, missions, pastoral care |
| 7000–7999 | Facility Expense | Mortgage, utilities, maintenance, insurance |
| 8000–8999 | Admin / Denominational | Supplies, legal, apportionments/assessments |
| 9000–9999 | Capital | Depreciation, capital expenditures, loan principal |

---

## Seed / Reference Data

### Existing church data files

- `backend/data/context_grace_umc.json` — full UMC sample (40+ accounts, 6 funds)
  Created by `coa_store.seed_sample_church()` on first startup.
- `backend/data/context_test_presbyterian.json` — Presbyterian test fixture

### Seed behavior

`startup()` in `main.py` calls `coa_store.ensure_seed()`. If `context_grace_umc.json`
does not exist, it calls `seed_sample_church()` and writes the file.

The `seed_sample_church()` function in `coa_store.py` (lines 152–302) is the canonical
reference for what a complete, well-structured church COA looks like.

---

## Key Dependencies

| Library | Version Spec | Purpose |
|---------|-------------|---------|
| fastapi | >=0.115.0 | REST API framework |
| uvicorn | >=0.32.0 | ASGI server |
| pydantic | >=2.9.0 | Data validation, models |
| crewai | >=0.86.0 | Multi-agent orchestration |
| chromadb | >=0.5.20 | Vector store for semantic COA search |
| sentence-transformers | >=3.3.0 | `all-MiniLM-L6-v2` embeddings (local) |
| anthropic | >=0.40.0 | Claude API for agent LLM calls |
| pypdf / pdfplumber | >=5.1.0 / >=0.11.4 | PDF extraction |
| python-frontmatter | >=1.1.0 | SKILL.md frontmatter parsing |
| fpdf2 | >=2.7.0 | Audit trail PDF generation |
| openpyxl / pandas | >=3.1.0 / >=2.2.0 | Spreadsheet COA import |
| python-dotenv | >=1.0.0 | `.env` loading |

Environment variable required: `ANTHROPIC_API_KEY` (loaded from `.env` at project root).

---

## Build / Run Commands

```bash
# Dev server (auto-reload)
./start.sh

# Manual equivalent
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Install dependencies
uv pip install -e .
```

No separate test runner is configured. No CI/CD files present.

---

## Open Questions for Church Profile Implementation

- UNCONFIRMED: Whether `fiscal_year_start` should always be January 1 or support
  non-calendar fiscal years (e.g., July 1 start for academic-year churches).
- UNCONFIRMED: AOG denomination has a `DenominationType` enum value but no corresponding
  `SKILL.md` or override dict. Treat as NONDENOMINATIONAL until added.
- UNCONFIRMED: `apportionment_accounts` field exists on `AccountingContext` but no UI
  surface to set it — only the seed data populates it.
- UNCONFIRMED: `parsonage_allowance_current_year` / `parsonage_allowance_used_ytd` fields
  are stored on the context but no endpoint exposes them for update separately from
  the full COA import.
- VERIFIED: Jobs are in-memory only. Any church profile feature requiring job
  history per church must account for this limitation.
- VERIFIED: ChromaDB index is rebuilt entirely on every COA mutation (no incremental
  update). This is fine for small COAs but will slow for large ones.

---

## Recommended Next Steps

1. Design the church profile creation UI/wizard — denomination selector drives which
   COA template is pre-populated.
2. Create denomination-specific COA templates as JSON (based on the seed data pattern
   and the SKILL.md account tables) for each supported denomination.
3. Decide whether `apportionment_accounts` and parsonage allowance fields need their
   own UI controls or are part of an "advanced" settings panel.
4. Consider whether the flat-JSON persistence is sufficient or whether a SQLite/Postgres
   store is needed (jobs are already identified as needing this).
5. Add an AOG denomination SKILL.md and keyword override dict to complete coverage.
