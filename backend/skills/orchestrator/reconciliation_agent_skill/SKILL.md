---
skill_name: reconciliation_agent
archetype: orchestrator
description: Wraps the MVP reconciliation_agent — pulls Plaid transactions, matches to pending JEs, surfaces exceptions.
inputs:
  - church_id
  - account_id
expected_output: Reconciliation summary with matched + exception counts.
allowed_tools:
  - plaid_sync
  - match_transactions
  - create_exception_card
privacy_class: P1
perturbations_emitted:
  - RECONCILIATION_EXCEPTION
---

# reconciliation_agent (MVP wrapper)
