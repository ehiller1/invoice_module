---
skill_name: denomination_episcopal
archetype: worker
description: >
  Episcopal Church (TEC) denomination-specific accounting rules. Covers diocesan assessment,
  rector compensation (Church Pension Fund, SECA, housing/rectory, COLA), endowment
  principal/income separation, Rector's Discretionary Fund, and Parochial Report compliance.
inputs:
  - accounting_context
  - classified_line_items
expected_output: >
  Episcopal-adjusted ClassifiedLineItems with CPF pension splits, diocesan assessment
  allocation, endowment income/principal separation, and discretionary fund tagging.
allowed_tools:
  - skill_load_tool
  - coa_semantic_search_tool
---

# Episcopal Church (TEC) — Denomination-Specific Accounting

## Diocesan Assessment (Fair Share / Asking)

Each parish pays an annual diocesan assessment based on plate and pledge income.
Assessment rates vary by diocese (typically 10–20% of operating income).

### Account Mapping
| Assessment | Account | Notes |
|-----------|---------|-------|
| Diocesan Assessment | 8410 | Primary obligation |
| National Church Pledge | 8420 | Through diocese to 815 2nd Ave |

### Detection Keywords → DENOMINATIONAL_ASSESSMENT
"diocesan assessment", "fair share", "the asking", "national church pledge",
"PB&F", "814 assessment", "diocese pledge", "conventional assessment"

## Rector / Clergy Compensation

### Housing
| Situation | Account | Notes |
|-----------|---------|-------|
| Rectory provided | In-kind | Church-owned; no W-2 housing value |
| Housing allowance | 5101 | Set by vestry resolution; canon requirement |
| Utility allowance (with rectory) | 5105 | For utilities in church-owned home |
| Both rectory + allowance | Prohibited | Cannot claim both simultaneously |

### Church Pension Fund (CPF) — Mandatory
ALL TEC clergy must be enrolled in CPF from The Church Pension Group.

| Contribution | Account | Rate (2024) |
|-------------|---------|-------------|
| CPF Employer (base) | 5210 | 18% of Defined Compensation |
| ECCA Supplemental | 5215 | Optional employer supplement |
| Healthcare (CPG) | 5220 | Varies by plan tier |
| Death & Disability | 5222 | Included in 18% rate |

CPF invoices quarterly; late payment (>30 days) incurs 1.5%/month penalty.
Keywords: "church pension", "CPG invoice", "CPF contribution", "ECCA"
→ Classification: BENEFITS, Account: 5210/5220/5222

### SECA for Clergy
Episcopal clergy are self-employed for Social Security.
- SECA reimbursement (if vestry approved) → Account 5150

## Endowment & Restricted Funds

### Endowment Fund (Permanently Restricted)
Per FASB ASC 958-205, endowment principal is permanently restricted.
| Component | Account | Treatment |
|-----------|---------|-----------|
| Endowment Principal | 1900 | Never expended; reported as permanently restricted net assets |
| Endowment Income — Unspent | 1910 | Temporarily restricted until appropriated |
| Endowment Draw (appropriated) | Transfer | Board resolution required; moves to operating |

### Rector's Discretionary Fund
A separate restricted fund under the rector's sole discretion for pastoral needs.
- **Receipts** → 4900 (Discretionary Fund Revenue)
- **Expenditures** → 6900 (Rector's Discretionary)
- Never co-mingled with vestry-controlled operating funds
- Parish audit should verify receipts and purpose

### Memorial Funds
Donor-designated memorials with WITH_RESTRICTION_PURPOSE class.
Expenditures require vestry vote to release restrictions.

### Capital Campaign Fund
Ring-fenced for specific project per campaign covenant; TEMP_RESTRICTED_PURPOSE.

### Detection Keywords
"endowment", "rector's discretionary", "memorial fund", "discretionary fund",
"capital campaign", "bequest", "planned giving", "named fund"

## Parochial Report (Annual TEC Requirement)
TEC requires annual Parochial Report submitted to Diocese and National Church.
Must separately disclose:
- Plate & pledge income (operating)
- Endowment draws
- Each clergy compensation component
- Total communicants and families

Accounts must be structured to extract these figures cleanly.

## Liturgical Supplies
| Item | Account |
|------|---------|
| Candles, incense, wine, wafers | 6100 (Worship & Liturgy) |
| Vestments, altar linens | 6110 (Vestments & Liturgical Items) |
| Bulletins/printing for liturgy | 8100 (Printing) |
| Hymnals, prayer books | 6200 (Christian Education) |

## Lay Employee Benefits
- CPG lay employee pension (optional) → 5210
- CPG healthcare for lay staff → 5220

## Finance/Audit Requirements
Canons require parish financial statements reviewed by Audit Committee and submitted
to Diocese. Parishes with revenue >$500k typically require CPA audit or review.
