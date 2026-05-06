---
skill_name: risk_assessor
archetype: reviewer
description: >
  Evaluate the misclassification risk of each invoice line item. Assigns risk_level
  (LOW | MEDIUM | HIGH | CRITICAL) and risk_score (0.0-1.0) based on confidence scores,
  amount thresholds, fund restriction exposure, vendor history, and description ambiguity.
inputs:
  - classified_line_items
  - draft_allocations
  - accounting_context
expected_output: >
  RiskAssessment with risk_level, risk_score, per_line_risks, aggregate_flags, and recommendations.
allowed_tools:
  - skill_load_tool
---

# Risk Assessor — Misclassification Risk Scoring

## Purpose
Score the probability that an invoice line item has been incorrectly classified or mapped
to an incorrect GL account or fund. Surface high-risk items for HITL escalation or
additional review before journal entry posting.

## Risk Factors

### Confidence-Based Risk (Base Score)
| Confidence Range | Base Score |
|----------------|------------|
| ≥ 0.90 | 0.05 |
| 0.80 – 0.89 | 0.25 |
| 0.70 – 0.79 | 0.50 |
| < 0.70 | 0.75 |

### Amplifiers (+added to base score)
| Factor | Score Impact |
|--------|-------------|
| Restricted fund exposure (purpose/permanent) | +0.15 |
| Amount within 15% of capitalisation threshold | +0.15 |
| Split allocation across 2+ funds | +0.10 |
| Housing allowance flag (IRS compliance risk) | +0.10 |
| Ambiguous description (misc, various, general, etc.) | +0.15 |
| Round-number amount ≥$500 with no itemization | +0.08 |
| First-time vendor for this expense category | +0.12 |
| Description triggers 2+ taxonomy categories | +0.10 |

### Mitigators (−subtracted from score)
| Factor | Score Reduction |
|--------|----------------|
| Confidence ≥ 0.95 | -0.10 |
| Already flagged for HITL (human will review) | -0.05 |
| Recurring vendor with consistent category history | -0.10 |
| GL hint on invoice matches recommended account | -0.08 |

## Risk Levels
| Score | Level |
|-------|-------|
| 0.00 – 0.19 | LOW |
| 0.20 – 0.39 | MEDIUM |
| 0.40 – 0.64 | HIGH |
| ≥ 0.65 | CRITICAL |

## Escalation Rules
- CRITICAL → always add to escalation_items for HITL gate
- HIGH + restricted fund → escalate
- MEDIUM/LOW → annotate in risk_assessment only; allow automated flow

## Output Schema
```json
{
  "risk_level": "MEDIUM",
  "risk_score": 0.35,
  "per_line_risks": [
    {
      "line_id": "L1",
      "risk_level": "MEDIUM",
      "risk_score": 0.35,
      "flags": ["restricted_fund_exposure", "ambiguous_description"],
      "recommendation": "Verify fund purpose matches expense before posting"
    }
  ],
  "aggregate_flags": ["one_or_more_restricted_fund_exposures"],
  "recommendations": ["Manual review recommended for restricted fund postings"]
}
```

## Recommended Actions by Level
| Level | Action |
|-------|--------|
| LOW | Automated approval |
| MEDIUM | Treasurer review |
| HIGH | Finance Committee review |
| CRITICAL | Do not post — Board/Auditor escalation |
