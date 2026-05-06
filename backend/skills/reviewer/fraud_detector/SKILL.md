---
skill_name: fraud_detector
archetype: reviewer
description: >
  Detect fraud signals in church invoices. Evaluates duplicate submissions, threshold
  gaming, vendor anomalies, personal benefit indicators, and structural red flags.
  Returns FraudAssessment with fraud_level, fraud_score, and actionable signals.
inputs:
  - invoice_document
  - classified_line_items
  - vendor_history
  - accounting_context
expected_output: >
  FraudAssessment with fraud_level, fraud_score, signals[], and recommended_action.
allowed_tools:
  - skill_load_tool
  - vendor_history_tool
---

# Fraud Detector — Church Invoice Fraud Assessment

## Purpose
Apply a structured fraud detection framework to each submitted invoice. Church finance
environments have known fraud risk patterns including check tampering, vendor collusion,
expense reimbursement fraud, fictitious vendor schemes, and threshold gaming.

## Signal Categories

### Category A — Document Integrity (High Weight)
| Signal | Score Impact |
|--------|-------------|
| Missing invoice number | +0.25 |
| Duplicate invoice number (same vendor) | +0.40 |
| Invoice date >60 days before submission | +0.20 |
| Invoice total ≠ sum of line items + tax | +0.35 |
| Backdated more than 1 fiscal year | +0.40 |

### Category B — Amount Patterns (Medium Weight)
| Signal | Score Impact |
|--------|-------------|
| Total within 10% below capitalisation threshold | +0.30 |
| Multiple invoices summing to just below threshold | +0.35 |
| Round dollar amount with no tax (services) | +0.12 |
| Amount >3x vendor's historical average | +0.25 |

### Category C — Vendor Anomalies (Medium Weight)
| Signal | Score Impact |
|--------|-------------|
| Vendor name appears to be an individual person | +0.18 |
| No verifiable vendor address | +0.12 |
| Vendor address matches staff/member address | +0.40 |
| First-time vendor, high-value invoice (>$1,000) | +0.15 |

### Category D — Classification Red Flags (Low Weight)
| Signal | Score Impact |
|--------|-------------|
| Personal benefit keywords (vacation, gift, bonus) | +0.28 |
| Benevolence payment with no memo documentation | +0.22 |
| Petty cash reimbursement without receipt detail | +0.20 |
| Clergy housing claim exceeds designation | +0.20 |

## Fraud Risk Levels
| Total Score | Level |
|------------|-------|
| 0.00 – 0.19 | LOW |
| 0.20 – 0.39 | MEDIUM |
| 0.40 – 0.59 | HIGH |
| ≥ 0.60 | CRITICAL |

## Recommended Actions
| Level | Action |
|-------|--------|
| LOW | APPROVE (standard workflow) |
| MEDIUM | FLAG_FOR_TREASURER |
| HIGH | FLAG_FOR_FINANCE_COMMITTEE |
| CRITICAL | ESCALATE_TO_AUDITOR (freeze posting) |

## Output Schema
```json
{
  "fraud_level": "MEDIUM",
  "fraud_score": 0.30,
  "signals": [
    {
      "signal_id": "AMOUNT_BELOW_THRESHOLD",
      "category": "B",
      "description": "Total $2,480 is 0.8% below the $2,500 capitalisation threshold",
      "weight": 0.30,
      "evidence": "Invoice total: $2,480.00; threshold: $2,500.00"
    }
  ],
  "recommended_action": "FLAG_FOR_TREASURER"
}
```

## Church-Specific Context
Church fraud most commonly occurs in:
1. **Accounts payable** — fictitious vendors, inflated invoices
2. **Payroll** — ghost employees, inflated hours
3. **Cash handling** — skimming from plate offerings
4. **Expense reimbursements** — personal purchases disguised as church expenses
5. **Check tampering** — altered payee/amount after signing

The fraud detector focuses on AP fraud signals, as this is the pipeline entry point.
