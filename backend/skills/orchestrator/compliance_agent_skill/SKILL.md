---
skill_name: compliance_agent
archetype: orchestrator
description: Wraps the MVP compliance_agent — checks fund restrictions, policies, donor intent.
inputs:
  - je_draft
  - church_id
expected_output: Compliance verdict (PASS | BLOCK | NEEDS_REVIEW) with reasons.
allowed_tools:
  - check_fund_restriction
  - create_policy_card
privacy_class: P1
perturbations_emitted:
  - FUND_RESTRICTION_VIOLATION
  - POLICY_VIOLATION
---

# compliance_agent (MVP wrapper)
