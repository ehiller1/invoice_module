---
skill_name: denomination_umc
archetype: worker
description: >
  United Methodist Church (UMC) denomination-specific accounting rules. Covers apportionment
  calculations, connectional giving, pastor compensation (SECA, housing, Wespath), Special
  Sunday pass-throughs, and GCFA-compliant fund separation.
inputs:
  - accounting_context
  - classified_line_items
expected_output: >
  UMC-adjusted ClassifiedLineItems with correct apportionment account mapping, Wespath
  benefit tagging, and Special Sunday pass-through separation.
allowed_tools:
  - skill_load_tool
  - coa_semantic_search_tool
---

# United Methodist Church — Denomination-Specific Accounting

## Connectional Giving (Apportionments)

UMC apportionments are covenantal obligations — NOT voluntary. Failure to pay in full
reduces the Annual Conference's funding to General Church causes.

### Apportionment Account Mapping
| Fund | Account | Typical % Net Revenue |
|------|---------|----------------------|
| World Service Fund | 8310 | ~1.8% |
| Episcopal Fund | 8320 | ~0.5% |
| General Church Administration | 8330 | ~0.3% |
| Annual Conference Assessment | 8340 | Varies by conference |
| District Superintendent Fund | 8350 | ~0.3% |
| Black College Fund | 8360 | ~0.3% |
| Africa University Fund | 8365 | ~0.15% |
| Ministerial Education Fund | 8370 | ~0.7% |
| Interdenominational Cooperation | 8380 | ~0.3% |

### Detection Keywords → Reclassify to DENOMINATIONAL_ASSESSMENT
"apportionment", "world service", "episcopal fund", "annual conference assessment",
"district superintendent", "ministerial education fund", "gc2024", "wespath invoice",
"black college fund", "africa university"

## Pastor's Compensation Package

### Housing
| Situation | Account | Treatment |
|-----------|---------|-----------|
| Parsonage provided | In-kind | No W-2 housing value; church pays utilities |
| Housing allowance | 5101 | Designated by Board of Trustees resolution pre-year |
| Equity allowance | 5102 | Optional; taxable |

### Wespath Benefits (Mandatory for Clergy)
| Benefit | Account | Notes |
|---------|---------|-------|
| CRSP Defined Benefit (employer) | 5210 | Required: 12% of plan compensation |
| CRSP Defined Contribution (employer) | 5215 | 3% DC match |
| UMPIP (supplemental) | 5216 | Optional employer match |
| CPP Health Insurance | 5220 | Through Wespath HealthFlex or United HealthCare |
| CPP Death & Disability | 5222 | Included in standard CPP |

Wespath invoices arrive quarterly. Classification: BENEFITS (not DENOMINATIONAL_ASSESSMENT).

### SECA Reimbursement
UMC clergy are self-employed for Social Security purposes.
- 50% SECA reimbursement → Account 5150
- Must be included in clergy W-2 Box 1 as income (then deductible on Schedule SE)

## Special Sundays (Pass-Through Funds)
Six General Church Special Sundays — 100% pass-through, never co-mingled with operating.

| Sunday | Season | Pass-Through Account |
|--------|--------|----------------------|
| Human Relations Day | January | 2810 |
| One Great Hour of Sharing | Lent | 2820 |
| Native American Ministries | Easter | 2830 |
| Peace with Justice | Pentecost | 2840 |
| World Communion | October | 2850 |
| United Methodist Student | November | 2860 |

Receipt entry: Debit 1100 (Cash), Credit 2810–2860
Remittance entry: Debit 2810–2860, Credit 1100

## Memorial / Endowment Funds
Memorial funds are WITH_RESTRICTION_PERMANENT. Expenditures require Board of Trustees
resolution with specific purpose match. Annual Conference may require annual reporting
of memorial fund balances.

## Lay Staff Benefits
- HealthFlex for lay employees → 5220
- UMC Death & Disability → 5222
- Lay pension (if offered) → 5210

## Finance Committee Requirements (¶258.4 BOD)
Per Book of Discipline, Finance Committee must:
- Review monthly financial statements
- Approve unbudgeted expenditures >$2,500 (or local policy threshold)
- Maintain 2-month operating reserve

## Audit Requirements
GCFA (General Council on Finance and Administration) requires annual Audit Review
Committee report. The Church Finance & Administration Handbook governs GAAP application
for UMC local churches.
