---
skill_name: denomination_catholic_parish
archetype: worker
description: >
  Catholic parish denomination-specific accounting rules. Covers diocesan cathedraticum,
  priest stipend/benefits structure, USCCB special collection pass-throughs, sacramental
  fund separation, school subsidy accounting, and cemetery fund ring-fencing.
inputs:
  - accounting_context
  - classified_line_items
expected_output: >
  Catholic-adjusted ClassifiedLineItems with cathedraticum allocation, sacramental offering
  separation, USCCB pass-through tagging, and school/cemetery fund ring-fencing.
allowed_tools:
  - skill_load_tool
  - coa_semantic_search_tool
---

# Catholic Parish — Denomination-Specific Accounting

## Diocesan Cathedraticum & Assessments

### Cathedraticum (Primary Canonical Tax)
The cathedraticum is a canonical obligation imposed by the Bishop (c. 1263 CIC).
Typically 8–12% of gross parish receipts. Not discretionary — canonical penalty for
non-payment.

| Assessment | Account | Notes |
|-----------|---------|-------|
| Cathedraticum | 8510 | Primary diocesan obligation |
| Diocesan Insurance Assessment | 8520 | Property/liability pool |
| Catholic Schools Office | 8530 | If parish has a school |
| Mission Assessment | 8540 | Diocesan mission fund |
| Priests' Retirement Fund | 8550 | Mandatory pension contribution |
| Deacon Ministry | 8560 | If parish has permanent deacons |

### Detection Keywords → DENOMINATIONAL_ASSESSMENT
"cathedraticum", "diocesan assessment", "bishop's tax", "priest retirement fund",
"mission assessment", "diocesan appeal", "bishop's annual appeal"

## Priest Compensation

Catholic priests are NOT employees for FICA purposes (self-employed ministers).
Compensation is a stipend plus in-kind benefits, per diocesan guidelines.

| Component | Account | Notes |
|----------|---------|-------|
| Monthly Stipend | 5010 | Diocesan minimum (typically $1,000–2,500/mo) |
| Housing (Rectory) | In-kind | Church-owned; no W-2 value |
| Utility Allowance | 5105 | For utilities in rectory |
| Automobile Allowance | 5110 | Per diocesan guidelines |
| Continuing Education | 5120 | Canon 279 requirement |
| Health Insurance | 5220 | Through diocesan plan |
| Priests' Retirement | 5210 | Through diocesan program (mandatory) |
| Vacation / Retreat | 5130 | Per c. 533 §2 (min 1 month vacation + retreat) |

### No Employer FICA Required
Priests are self-employed ministers → no employer Social Security withholding.

## USCCB Special Collections (100% Pass-Through)
These are national collections mandated by the USCCB. Every dollar received is remitted;
NEVER co-mingle with parish operating funds.

| Collection | Season | Pass-Through Acct |
|-----------|--------|-------------------|
| Catholic Relief Services (Operation Rice Bowl) | Lent / Ash Wed | 2910 |
| Peter's Pence | June 29 (Feast of SS Peter & Paul) | 2920 |
| Home Missions (Catholic Extension) | Pentecost | 2930 |
| Christmas Joy (Black/Native seminarians) | Christmas | 2940 |
| Church in Latin America | October | 2950 |
| Catholic University of America | November | 2960 |
| Bishop's Annual Appeal | Diocesan | 2970 |
| Poor Box / St. Vincent de Paul | Ongoing | 2980 |

Receipt: Debit 1100 (Cash), Credit 291x–298x
Remittance: Debit 291x–298x, Credit 1100

Detection: "USCCB", "peter's pence", "CRS", "operation rice bowl", "Catholic relief",
"bishop's appeal", "SVDP", "St. Vincent de Paul"

## Sacramental Offerings

Sacramental fees/offerings cannot be mandatory (c. 848 CIC) but are tracked separately.

| Sacrament | Account | Notes |
|---------|---------|-------|
| Wedding offerings | 4500 | Voluntary; no set fee |
| Funeral offerings | 4510 | Priest's canonical stipend |
| Mass intentions (stipends) | 4520 | Max set by diocese; typically $10–15/Mass |
| Baptism offerings | 4530 | Voluntary |
| Marriage preparation fees | 4540 | Permitted as cost recovery |

## Catholic School Subsidy
If the parish sponsors or subsidizes a Catholic school, the school is a SEPARATE
accounting entity. The parish subsidy must be clearly disclosed.

| Item | Account |
|------|---------|
| Operating subsidy to school | 6800 (School Subsidy) |
| Capital contribution to school | 9300 (Capital — School) |
| Subsidy from school to parish | 4800 (Revenue — School Contribution) |

## Cemetery Fund (If Parish Operates Cemetery)
Cemetery is a SEPARATE fund under most diocesan guidelines. No co-mingling.
- **Cemetery Operations** → Separate fund, GENERAL_OPERATING
- **Perpetual Care Fund** → PERMANENTLY_RESTRICTED; only income spendable
- Invoices for cemetery maintenance must be coded to cemetery fund, not parish operating

## Religious Education (CCD/PSR/RCIA)
| Program | Account |
|---------|---------|
| CCD / PSR materials | 6200 (Religious Education) |
| RCIA program | 6210 (RCIA) |
| Confirmation prep | 6200 |
| Faith formation stipends | 5050 (Part-time staff) |

## Finance Council (c. 537 CIC)
Every parish must have a Finance Council. Finance Council must:
- Review annual budget
- Review financial reports (at least quarterly)
- Advise pastor on expenditures above diocesan threshold (typically $5,000–10,000)
Pastor cannot make extraordinary expenditures without Finance Council consent (c. 1281).
