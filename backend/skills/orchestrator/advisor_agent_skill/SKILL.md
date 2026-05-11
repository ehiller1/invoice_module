---
skill_name: advisor_agent
archetype: orchestrator
description: Wraps the MVP advisor_agent — answers questions about the decision ledger, CoA, and variance reports.
inputs:
  - question
  - church_id
expected_output: Conversational answer with citations.
allowed_tools:
  - query_decision_ledger
  - semantic_search_coa
  - get_variance_report
privacy_class: P1
perturbations_emitted: []
---

# advisor_agent (MVP wrapper)
