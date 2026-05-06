---
skill_name: denomination_presbyterian
archetype: worker
description: >
  Presbyterian Church USA (PCUSA) denomination-specific accounting rules. Covers per capita
  apportionment (GA/Synod/Presbytery), Mission Co-Investment offerings, Terms of Call
  compensation, Board of Pensions obligations, manse-vs-allowance treatment, and
  session-designated fund management.
inputs:
  - accounting_context
  - classified_line_items
expected_output: >
  PCUSA-adjusted ClassifiedLineItems with per capita allocation, BOP pension tagging,
  Terms of Call component separation, and session-restricted fund classification.
allowed_tools:
  - skill_load_tool
  - coa_semantic_search_tool
---

# Presbyterian Church USA (PCUSA) — Denomination-Specific Accounting

## Per Capita Apportionment

Per capita is a per-communing-member assessment flowing through three Presbyterian
governing bodies. It is set annually by each body and is a constitutional obligation.

### Per Capita Account Structure
| Level | Account | 2024 Rate |
|-------|---------|-----------|
| General Assembly per capita | 8710 | ~$9.50/member |
| Synod per capita | 8720 | Varies by Synod |
| Presbytery per capita | 8730 | Varies by Presbytery |
| Total Per Capita | 8700 | Sum of above |

### Calculation
Per Capita = rate × active communing members on roll (as of December 31 prior year)

### Detection Keywords → DENOMINATIONAL_ASSESSMENT, 8700 range
"per capita", "per-capita", "GA per capita", "general assembly assessment",
"synod per capita", "presbytery per capita", "per capita apportionment"

## Mission Co-Investment Offerings (Pass-Through)

PCUSA voluntary mission giving channels — 100% pass-through to recipients.

| Offering | Season | Pass-Through Acct |
|---------|--------|-------------------|
| One Great Hour of Sharing | Lent | 2710 |
| Pentecost Offering | Pentecost | 2720 |
| Peace & Global Witness | World Communion Sunday | 2730 |
| Christmas Joy | Advent | 2740 |
| Presbyterian Disaster Assistance | As needed | 2750 |

Receipt: Debit 1100, Credit 271x–275x
Remittance: Debit 271x–275x, Credit 1100

## Terms of Call (TOC)

The Terms of Call is the binding compensation document for all called ministers.
It is approved by the Session and confirmed by Presbytery (per G-2.0804 PCUSA BOO).

### TOC Components
| Component | Account | Notes |
|----------|---------|-------|
| Cash Salary | 5010 | Must meet Presbytery minimum salary |
| Housing Allowance | 5101 | Session resolution required; pre-year designation |
| Manse Rental Value | In-kind | Church-owned; no W-2 value |
| Manse Utility Allowance | 5105 | If manse provided |
| Social Security Supplement | 5150 | 50% SECA required by most Presbyteries |
| Study Leave Allowance | 5120 | Minimum $1,000/yr typical; G-2.0804 |
| Professional Expenses | 5125 | Books, journals, professional dues |
| Vacation | Policy | Minimum 4 weeks per BOO |
| Continuing Education Leave | Policy | Minimum 2 weeks per BOO |

### Manse vs. Housing Allowance — Mutual Exclusivity
- **Manse provided**: No housing allowance on W-2; utility/maintenance allowance OK
- **Housing allowance**: Session pre-year designation; IRS exclusion from income tax
- **BOTH are prohibited** — cannot claim allowance value AND in-kind manse benefit

### SECA for PCUSA Clergy
PCUSA ministers are self-employed for Social Security. Most Presbyteries require
the congregation to pay a Social Security supplement (typically 50% of SECA).
This supplement is taxable income but offsets the minister's self-employment tax burden.

## Board of Pensions (BOP)

All called PCUSA ministers must be enrolled in BOP (The Board of Pensions of PCUSA).
Lay employee enrollment is optional but available.

### Employer Contributions
| Plan | Account | 2024 Rate |
|------|---------|-----------|
| Defined Benefit Pension (DBPP) | 5210 | 36.5% of effective salary |
| Death & Disability | 5222 | Included in DBPP rate |
| Healthcare (if enrolled) | 5220 | Varies: $500–900/mo depending on tier |
| Supplemental Retirement (optional) | 5215 | Additional employer contribution |

Detection: "board of pensions", "BOP invoice", "BOP contribution", "PCUSA pension"
→ Classification: BENEFITS, Account 5210/5220

## Session-Designated Restricted Funds

| Fund Type | Description | Accounting Class |
|-----------|-------------|-----------------|
| Board-Designated Reserve | Session voted discretionary reserve | BOARD_DESIGNATED |
| Building Reserve | Capital maintenance fund | TEMP_RESTRICTED_PURPOSE |
| Mission Fund | Local outreach support | TEMP_RESTRICTED_PURPOSE |
| Scholarship Fund | Member educational aid | TEMP_RESTRICTED_PURPOSE |
| Endowment | If exists; per BOP guidance | PERMANENTLY_RESTRICTED |

Session resolutions must be recorded in minutes; restrictions cannot be lifted without
a counter-resolution and (for externally restricted funds) donor consent.

## Presbyterian Women (PW) Funds

PW is a separate organization within TEC. PW funds are SEPARATE from parish funds.
- PW contributions to church → Revenue 4800
- Church contributions to PW programs → Expense 6500 (Mission Support)
- Never co-mingle PW operational accounts with parish accounts

## Audit / Financial Review Requirements

Per G-3.0113 PCUSA BOO, every congregation must conduct an annual financial review
or audit by a committee of the congregation not including the treasurer. Larger congregations
(typically >$500k revenue) should engage a CPA firm.
