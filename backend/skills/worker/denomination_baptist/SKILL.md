---
skill_name: denomination_baptist
archetype: worker
description: >
  Baptist/SBC denomination-specific accounting rules. Covers Cooperative Program giving
  and split, Lottie Moon/Annie Armstrong pass-throughs, pastor housing allowance, GuideStone
  benefits, designated gifts culture, Deacon Fund, and autonomous local church accounting.
inputs:
  - accounting_context
  - classified_line_items
expected_output: >
  Baptist-adjusted ClassifiedLineItems with CP split allocation, special offering pass-through
  tagging, pastor housing allowance flagging, and designated fund separation.
allowed_tools:
  - skill_load_tool
  - coa_semantic_search_tool
---

# Baptist / SBC — Denomination-Specific Accounting

## Cooperative Program (CP) Giving

The Cooperative Program is SBC's primary unified mission giving channel. Unlike
apportionments, CP is voluntary — but most SBC churches budget a percentage of
undesignated receipts (typically 5–15%).

### CP Account Structure
| Level | Account | Typical Split |
|-------|---------|--------------|
| Total CP Giving | 8600 | 100% of CP gift |
| ↳ State Convention | 8610 | 50–60% of CP total |
| ↳ SBC National (IMB, NAMB, seminaries) | 8620 | 40–50% of CP total |

### Detection Keywords → DENOMINATIONAL_ASSESSMENT, Account 8600
"cooperative program", "CP giving", "state convention giving", "SBC cooperative",
"association missions", "associational missions dues"

## Special Mission Offerings (100% Pass-Through)
These are designated offerings collected and fully remitted. Never co-mingled with operating.

| Offering | Season | Pass-Through Acct |
|---------|--------|-------------------|
| Lottie Moon Christmas Offering (IMB) | Christmas | 2610 |
| Annie Armstrong Easter Offering (NAMB) | Easter | 2620 |
| State Mission Offering | Fall | 2630 |
| World Hunger Fund | Ongoing | 2640 |
| Church Planting Offering (local) | Varies | 2650 |

Receipt: Debit 1100, Credit 261x–265x
Remittance: Debit 261x–265x, Credit 1100

Detection: "lottie moon", "annie armstrong", "state mission offering",
"hunger fund", "world hunger", "IMB offering", "NAMB offering"

## Pastor Compensation

### Housing Allowance (Critical IRS Rule)
Baptist pastors are employees for income tax but self-employed for Social Security.
Most Baptist churches provide housing allowance per IRS §107.

| Component | Account | Notes |
|----------|---------|-------|
| Cash Salary | 5010 | W-2 Box 1 income |
| Housing Allowance | 5101 | Excluded from federal/state income tax ONLY |
| Auto Allowance | 5110 | Per IRS accountable plan or W-2 if unaccountable |
| Convention/Education | 5120 | Accountable plan reimbursement |
| Life Insurance | 5220 | If group plan |
| Health Insurance | 5221 | |
| GuideStone Annuity | 5210 | Employer contribution |
| SECA Reimbursement | 5150 | 50% of self-employment tax; if offered |

### Housing Allowance IRS Rules
- Must be designated by church/deacon board BEFORE the year it applies
- Excludable amount = lesser of: (1) designated allowance, (2) actual housing expenses,
  (3) fair rental value of home furnished
- NOT exempt from self-employment (Social Security) tax
- Resolution must be documented in church minutes before January 1

### GuideStone Financial Resources
SBC pension/benefits through GuideStone (formerly Annuity Board of SBC).
| Plan | Account |
|------|---------|
| Retirement contribution | 5210 |
| Health plan premium | 5221 |
| Life/disability | 5222 |

## Deacon Fund (Benevolence)
Deacons administer a discretionary benevolence fund. This is a restricted fund.

| Transaction | Account | Notes |
|------------|---------|-------|
| Donations received for Deacon Fund | 4600 | Restricted receipt |
| Deacon Fund disbursements | 6910 | Benevolence expenditure |

- Individual disbursements typically not disclosed (donor/recipient privacy)
- Fund is WITH_RESTRICTION_PURPOSE (only for benevolence/pastoral care)
- No individual payments >$600 per IRS 1099 rules without proper reporting

## Designated Gift Culture

Baptist churches have extensive designated gift accounting. Each designated gift creates
a restricted account obligation.

| Common Designations | Fund Type |
|--------------------|-----------|
| Youth mission trip fund | TEMP_RESTRICTED_PURPOSE |
| Building fund | CAPITAL_CAMPAIGN or TEMP_RESTRICTED_PURPOSE |
| Media/technology fund | TEMP_RESTRICTED_PURPOSE |
| Children's ministry fund | TEMP_RESTRICTED_PURPOSE |
| Library/resource fund | BOARD_DESIGNATED |

### Rules
- Unexpended designated funds MUST be retained for their purpose
- Cannot redirect to operating without donor consent
- If purpose becomes impossible, contact donor or follow cy-pres doctrine
- Keywords: "designated for", "given toward", "in memory of", "restricted to"

## Autonomous Local Church Note
Baptist churches have NO hierarchical authority. These rules reflect GuideStone
Financial Resources and Baptist Church Administrators Association (BCAA) best practices.
Individual churches may deviate; always defer to the church's stated policy.
