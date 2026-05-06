---
skill_name: expense_taxonomy_v1
archetype: worker
description: Reference taxonomy of 40+ church expense categories with keyword triggers and ministry area mappings. Loaded by line_item_classifier.
inputs:
  - description
expected_output: Candidate expense_category list with confidence scores.
allowed_tools:
  - skill_resource_tool
---

# expense_taxonomy_v1

## Categories (account range, keyword triggers, ministry area hint)

- CLERGY_COMPENSATION (5100): pastor salary, clergy stipend
- CLERGY_HOUSING (5100): parsonage utilities, manse repairs, rectory
- LAY_STAFF_WAGES (5200): admin salary, music director, nursery staff
- BENEFITS (5300): health insurance, retirement contribution, dental
- SECA_REIMBURSEMENT (5110): SECA, self-employment tax
- WORSHIP (6100): altar flowers, communion supplies, sound system, sheet music | ministry=WORSHIP
- CHILDREN_MINISTRY (6200): VBS, Sunday school curriculum, nursery supplies | ministry=CHILDREN
- YOUTH_MINISTRY (6300): youth retreat, camp fees, snacks | ministry=YOUTH
- ADULT_EDUCATION (6400): adult class, small group materials | ministry=ADULT_EDUCATION
- MISSIONS (6500-6600): missionary support, mission trip, world relief | ministry=MISSIONS
- PASTORAL_CARE (6700): visitation, hospital, bereavement | ministry=PASTORAL_CARE
- MORTGAGE_RENT (7100): mortgage payment, lease, principal+interest
- UTILITIES (7200): electric, gas, water, sewer, trash, internet, phone
- MAINTENANCE_REPAIRS (7300): hvac repair, plumbing, roof, painting, lawn
- INSURANCE (7400): liability insurance, property insurance, workers comp
- TECHNOLOGY (7500): software subscription, computer, server, av equipment
- OFFICE_SUPPLIES (8100): paper, toner, pens, postage
- LEGAL_AUDIT (8200): attorney, cpa, audit fees
- DENOMINATIONAL_ASSESSMENT (8300): diocesan apportionment, conference asking
- STEWARDSHIP_FUNDRAISING (8400): pledge cards, capital campaign costs
- CAPITAL_EXPENDITURE (9200): building addition, new hvac unit (>threshold)
- EQUIPMENT (9200): copier, vehicle, large appliance (>threshold)
- IMPROVEMENT (9200): parking lot resurface, sanctuary remodel
- LOAN_PRINCIPAL (9300): loan principal payment
- BENEVOLENCE: aid to individual, emergency assistance
