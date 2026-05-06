# Research: Episcopal Church Accounting & Profile Configuration
Generated: 2026-05-06
Source files verified: denomination_episcopal/SKILL.md, context_grace_umc.json, denomination_rules.py, schemas.py, EIME-church-profile-architecture.md

---

## 1. Episcopal Denomination Rules (SKILL.md — VERIFIED)

File: `backend/skills/worker/denomination_episcopal/SKILL.md`

### 1.1 Diocesan Assessment

The primary Episcopal-specific financial obligation. Each parish pays an annual assessment based on plate and pledge income.

- Rate: typically 10–20% of operating income (varies by diocese)
- Primary account: **8410** (Diocesan Assessment)
- National Church Pledge account: **8420** (flows through diocese to 815 2nd Ave, New York)
- Classification override: `DENOMINATIONAL_ASSESSMENT`

Detection keywords (trigger the override in `denomination_rules.py`):
```
"diocesan assessment", "fair share", "the asking", "national church pledge",
"PB&F", "814 assessment", "diocese pledge", "conventional assessment"
```

For `apportionment_accounts` in the JSON profile, Episcopal uses accounts 8410/8420 rather than 8300/8310 as UMC does.

### 1.2 Clergy Compensation

**Housing:**
| Situation | Account | Notes |
|-----------|---------|-------|
| Rectory provided (church-owned) | In-kind | No W-2 housing value; not a cash expense |
| Housing allowance (cash) | 5101 | Set by vestry resolution; canon requirement |
| Utility allowance with rectory | 5105 | For utilities in church-owned home |
| Both rectory + allowance | PROHIBITED | Cannot claim both simultaneously |

**Church Pension Fund (CPF) — MANDATORY for all TEC clergy:**
| Contribution | Account | Rate (2024) |
|-------------|---------|-------------|
| CPF Employer (base) | **5210** | 18% of Defined Compensation |
| ECCA Supplemental | **5215** | Optional employer supplement |
| Healthcare (CPG) | **5220** | Varies by plan tier |
| Death & Disability | **5222** | Included in 18% CPF rate |

CPF invoices quarterly. Late payment (>30 days) incurs 1.5%/month penalty.
Detection keywords: `"church pension"`, `"CPG invoice"`, `"CPF contribution"`, `"ECCA"`
Classification: `BENEFITS`, Account: 5210/5220/5222

**SECA Reimbursement:**
- Episcopal clergy are self-employed for Social Security
- SECA reimbursement (if vestry-approved) → Account **5150**

**Clergy salary base:** Account **5100**

### 1.3 Endowment & Restricted Funds

Per FASB ASC 958-205, endowment principal is permanently restricted.

| Component | Account | Treatment |
|-----------|---------|-----------|
| Endowment Principal | **1900** | Never expended; permanently restricted net assets |
| Endowment Income — Unspent | **1910** | Temporarily restricted until appropriated |
| Endowment Draw (appropriated) | Transfer entry | Board resolution required; moves to operating |

**Rector's Discretionary Fund** (unique to Episcopal):
- Receipts → **4900** (Discretionary Fund Revenue)
- Expenditures → **6900** (Rector's Discretionary)
- Never co-mingled with vestry-controlled operating funds
- Parish audit must verify receipts and purpose

**Memorial Funds:**
- Restriction class: `WITH_RESTRICTION_PURPOSE`
- Expenditures require vestry vote to release restrictions

**Capital Campaign Fund:**
- Ring-fenced for specific project per campaign covenant
- Fund category: `TEMP_RESTRICTED_PURPOSE`

Detection keywords for restricted funds:
```
"endowment", "rector's discretionary", "memorial fund", "discretionary fund",
"capital campaign", "bequest", "planned giving", "named fund"
```

### 1.4 Liturgical Supplies (Episcopal-specific accounts)

| Item | Account |
|------|---------|
| Candles, incense, wine, wafers | **6100** (Worship & Liturgy) |
| Vestments, altar linens | **6110** (Vestments & Liturgical Items) |
| Bulletins/printing for liturgy | **8100** (Printing) |
| Hymnals, prayer books | **6200** (Christian Education) |

### 1.5 Parochial Report (Annual TEC Requirement)

TEC requires annual Parochial Report submitted to Diocese and National Church. Must separately disclose:
- Plate & pledge income (operating)
- Endowment draws
- Each clergy compensation component
- Total communicants and families

Accounts must be structured to extract these figures cleanly. This means the COA must NOT aggregate clergy compensation into a single line.

### 1.6 Finance/Audit Requirements

- Parish financials reviewed by Audit Committee, submitted to Diocese
- Parishes with revenue >$500k typically require CPA audit or review

---

## 2. AccountingContext Data Structure (VERIFIED)

File: `backend/models/schemas.py`

The JSON profile must conform to `AccountingContext`. All fields:

```json
{
  "church_id": "string — slug, e.g. holy_comforter_episcopal",
  "church_name": "string — display name",
  "denomination_type": "EPISCOPAL",
  "fiscal_year": 2026,
  "fiscal_year_start": "2026-01-01",
  "accounts": [ ... ],
  "funds": [ ... ],
  "allocation_schedules": [ ... ],
  "capitalisation_threshold_usd": "2500",
  "parsonage_allowance_current_year": "0",
  "parsonage_allowance_used_ytd": "0",
  "apportionment_accounts": [ ... ],
  "warnings": []
}
```

**Notes on Episcopal-specific fields:**
- `parsonage_allowance_current_year`: Use 0 if rectory (church-owned property); use actual dollar amount if vestry-set cash housing allowance
- `parsonage_allowance_used_ytd`: Running YTD tracker — set to 0 at profile creation
- `apportionment_accounts`: Use accounts 8410/8420 with the diocese-specific percentage (not 8300/8310 as UMC uses)

### Account Object

```json
{
  "account_number": "5210",
  "account_name": "Church Pension Fund (CPF)",
  "account_type": "Expense",
  "fund_id": "GEN",
  "restriction_class": "WITHOUT_RESTRICTION",
  "active": true
}
```

`account_type` valid values (from schema + seed data): `"Asset"`, `"Liability"`, `"Equity"`, `"Revenue"`, `"Expense"`

### Fund Object

```json
{
  "fund_id": "DISC",
  "fund_name": "Rector's Discretionary Fund",
  "restriction_class": "WITH_RESTRICTION_PURPOSE",
  "fund_category": "BOARD_DESIGNATED",
  "purpose_description": "Pastoral aid under rector's sole discretion",
  "expenditure_rules": "Rector discretion; never co-mingled with operating",
  "current_balance": "0"
}
```

### RestrictionClass values (VERIFIED from schemas.py)
- `"WITHOUT_RESTRICTION"` — operating/unrestricted funds
- `"WITH_RESTRICTION_PURPOSE"` — temporarily restricted for a stated purpose
- `"WITH_RESTRICTION_PERMANENT"` — permanently restricted (endowment principal)

### FundCategory values (VERIFIED from schemas.py)
- `"GENERAL_OPERATING"` — day-to-day unrestricted
- `"TEMP_RESTRICTED_PURPOSE"` — donor-restricted by purpose
- `"TEMP_RESTRICTED_TIME"` — time-released restriction
- `"PERMANENTLY_RESTRICTED"` — endowment principal
- `"BOARD_DESIGNATED"` — vestry-designated (rector's discretionary, reserves)
- `"CAPITAL_CAMPAIGN"` — ring-fenced capital project

---

## 3. Account Number Conventions (VERIFIED from seed data + architecture doc)

| Range | Type | Episcopal Usage |
|-------|------|----------------|
| 1000–1099 | Cash/Liquid Assets | Operating checking, savings |
| 1010–1030 | Cash by fund | Fund-specific cash accounts |
| 1500–1599 | Fixed Assets | Land, buildings, equipment |
| 1900 | Endowment Principal | Permanently restricted investment |
| 1910 | Endowment Income (unspent) | Temporarily restricted until appropriated |
| 2010–2030 | Liabilities | AP, payroll liabilities |
| 3100 | Net Assets — Without Restriction | |
| 3200 | Net Assets — Purpose Restricted | |
| 3300 | Net Assets — Endowment | |
| 4100 | Tithes & Offerings (plate + pledge) | Primary revenue for Parochial Report |
| 4200–4220 | Designated Gifts by fund | |
| 4900 | Discretionary Fund Revenue | Rector's Discretionary receipts |
| 5100 | Clergy Salary | Base cash salary |
| 5101 | Housing Allowance | Vestry-set; 0 if rectory provided |
| 5105 | Utility Allowance (with rectory) | |
| 5150 | SECA Reimbursement | |
| 5200 | Lay Staff Wages | |
| 5210 | CPF Employer Pension | 18% of Defined Compensation |
| 5215 | ECCA Supplemental | Optional |
| 5220 | CPG Healthcare | |
| 5222 | Death & Disability | |
| 6100 | Worship & Liturgy | Candles, wine, wafers, incense |
| 6110 | Vestments & Liturgical Items | |
| 6200 | Christian Education / Children | Hymnals, prayer books, formation |
| 6700 | Pastoral Care | |
| 6900 | Rector's Discretionary Expenditures | |
| 7100 | Mortgage/Rent | |
| 7200–7230 | Utilities | Electric, gas, water, internet |
| 7300–7320 | Maintenance & Grounds | |
| 7400 | Insurance | |
| 7500 | Technology | |
| 8100 | Printing / Bulletins | |
| 8200 | Legal & Audit | |
| 8410 | Diocesan Assessment (Fair Share) | Primary Episcopal apportionment |
| 8420 | National Church Pledge | |
| 9100 | Depreciation | |
| 9200–9210 | Capital Expenditures | |
| 9300 | Loan Principal | |

---

## 4. Fund Structure for Episcopal Churches

### Universal Funds (present in all denominations)

| fund_id | fund_name | restriction_class | fund_category |
|---------|-----------|-------------------|---------------|
| GEN | General Operating Fund | WITHOUT_RESTRICTION | GENERAL_OPERATING |

### Episcopal-Standard Funds

| fund_id | fund_name | restriction_class | fund_category | Notes |
|---------|-----------|-------------------|---------------|-------|
| GEN | General Operating | WITHOUT_RESTRICTION | GENERAL_OPERATING | All unrestricted ops |
| DISC | Rector's Discretionary | WITH_RESTRICTION_PURPOSE | BOARD_DESIGNATED | Rector sole control |
| MEM | Memorial Fund | WITH_RESTRICTION_PURPOSE | TEMP_RESTRICTED_PURPOSE | Donor-designated |
| ENDOW | Endowment Fund | WITH_RESTRICTION_PERMANENT | PERMANENTLY_RESTRICTED | Principal never spent |
| BLDG | Building/Capital Fund | WITH_RESTRICTION_PURPOSE | CAPITAL_CAMPAIGN | Capital projects |
| MISS | Missions Fund | WITH_RESTRICTION_PURPOSE | TEMP_RESTRICTED_PURPOSE | Outreach/pass-through |

### Episcopal-Specific Fund Notes
- **No equivalent to UMC's "Special Sundays" pass-through accounts** (accounts 2810–2860). Episcopal pass-throughs are handled via designated gifts to specific mission funds.
- Rector's Discretionary is Episcopal-specific (no direct UMC/Presbyterian parallel). It uses `BOARD_DESIGNATED` category because vestry designates it but rector controls disbursements.
- Endowment income unspent stays in `ENDOW` fund with account 1910 until a board resolution appropriates it to operating.

---

## 5. Denomination-Specific Keyword Overrides (VERIFIED from denomination_rules.py)

These are the patterns the classification engine uses to auto-detect and override categories:

```python
_EPISCOPAL_OVERRIDES = [
    (["diocesan assessment", "fair share", "the asking", "national church pledge",
      "pb&f", "diocesan pledge"],
     "DENOMINATIONAL_ASSESSMENT", "8410"),
    (["church pension", "cpg invoice", "cpf contribution", "ecca"],
     "BENEFITS", "5210"),
    (["rector's discretionary", "discretionary fund"],
     "PASTORAL_CARE", "6900"),
    (["endowment", "planned giving", "bequest"],
     "UNKNOWN", "1900"),
]
```

Note: "conventional assessment" and "814 assessment" appear in the SKILL.md keyword list but NOT in denomination_rules.py. The SKILL.md list is more comprehensive (used by agents); denomination_rules.py is the fast keyword-match fallback.

---

## 6. Universal vs. Episcopal-Specific Accounts

### Universal (present in UMC, Presbyterian, Episcopal — use same numbers)
- 1010 Operating Cash
- 2010 Accounts Payable
- 2030 Payroll Liabilities
- 3100 Net Assets — Without Restriction
- 3300 Net Assets — Endowment
- 4100 Tithes & Offerings
- 5100 Clergy Compensation — Salary
- 5101 Housing Allowance
- 5150 SECA Reimbursement
- 5200 Lay Staff Wages
- 5210 Benefits — Pension (employer)
- 5220 Benefits — Healthcare
- 5222 Benefits — Death & Disability
- 6200 Christian Education / Children's Ministry
- 7100–7320 Facility expenses (mortgage, utilities, maintenance, grounds)
- 7400 Insurance
- 8100–8200 Office/Admin/Legal
- 9100–9300 Capital

### Episcopal-Specific (no direct UMC parallel)
- **5215** — ECCA Supplemental (CPF-specific supplement, not Wespath)
- **5105** — Utility Allowance with rectory (distinct from parsonage situation)
- **6110** — Vestments & Liturgical Items (explicit TEC category)
- **4900** — Discretionary Fund Revenue (rector's fund receipts)
- **6900** — Rector's Discretionary Expenditures
- **8410** — Diocesan Assessment (replaces UMC's 8300 Conference Apportionment)
- **8420** — National Church Pledge (replaces UMC's 8310 District Apportionment)
- **1900** — Endowment Principal (UMC uses 3300 equity approach; TEC tracks as asset)
- **1910** — Endowment Income — Unspent

### UMC Accounts NOT used in Episcopal
- 8300 Denominational Apportionment — Conference → use 8410 instead
- 8310 Denominational Apportionment — District → use 8420 instead
- 5215/5216 (CRSP DC / UMPIP) → not relevant; CPF uses different supplemental structure
- 2810–2860 Special Sunday pass-through liabilities → not a TEC pattern

---

## 7. Holy Comforter Episcopal Church — Profile Configuration Notes

For `context_holy_comforter_episcopal.json`:

### Required top-level fields
```json
{
  "church_id": "holy_comforter_episcopal",
  "church_name": "Church of the Holy Comforter",
  "denomination_type": "EPISCOPAL",
  "fiscal_year": 2026,
  "fiscal_year_start": "2026-01-01"
}
```

### Housing allowance fields
- If rector lives in church-owned rectory: set `parsonage_allowance_current_year` to `"0"`, rely on 5105 for utility allowance
- If rector receives cash housing allowance: set to the vestry-resolution dollar amount (e.g., `"36000"`)

### Apportionment accounts
Episcopal uses 8410/8420 with the diocese-specific percentage (e.g., Diocese of Virginia uses ~15% fair share):
```json
"apportionment_accounts": [
  { "account_number": "8410", "pct_of_revenue": "15.0" },
  { "account_number": "8420", "pct_of_revenue": "0.0" }
]
```
Note: National Church Pledge is often folded into the diocesan assessment total — confirm with actual diocese billing.

### Capitalisation threshold
Standard: `"2500"` (same as UMC seed data).

### Funds — recommended minimum set
1. GEN — General Operating (WITHOUT_RESTRICTION / GENERAL_OPERATING)
2. DISC — Rector's Discretionary (WITH_RESTRICTION_PURPOSE / BOARD_DESIGNATED)
3. ENDOW — Endowment Fund (WITH_RESTRICTION_PERMANENT / PERMANENTLY_RESTRICTED) — include only if church has an endowment
4. BLDG — Building Fund (WITH_RESTRICTION_PURPOSE / CAPITAL_CAMPAIGN) — include if active capital campaign or reserves exist
5. MISS — Missions (WITH_RESTRICTION_PURPOSE / TEMP_RESTRICTED_PURPOSE) — include if church has designated mission giving

### Key accounts to include (minimum for Parochial Report compliance)
- Separate accounts for: plate/pledge revenue (4100), housing (5101), each CPF component (5210/5220/5222), diocesan assessment (8410), rector's discretionary (6900)
- The Parochial Report requires each clergy compensation component to be separately extractable — do NOT collapse 5100/5101/5210/5220 into a single account

---

## 8. File Naming & Creation

File: `backend/data/context_holy_comforter_episcopal.json`

Created via API: `POST /api/churches` with body:
```json
{
  "church_id": "holy_comforter_episcopal",
  "church_name": "Church of the Holy Comforter",
  "denomination_type": "EPISCOPAL",
  "fiscal_year": 2026
}
```
Then populated via `POST /api/churches/holy_comforter_episcopal/coa/import` with full accounts/funds JSON.

