---
skill_name: allocation_reviewer
archetype: reviewer
description: Validate draft line allocations against fund restriction rules, the church's expenditure policies, and the expected_output schema. Approve, request revision, or escalate for HITL.
inputs:
  - draft_allocations
  - accounting_context
  - document_type
expected_output: ReviewedAllocations with per-line verdicts, overall_verdict, escalation_items, revision_items, review_notes.
allowed_tools:
  - skill_load_tool
  - fund_restriction_checker_tool
---

# allocation_reviewer

## Workflow Steps

1. Load fund_restriction_checker_tool schema.
2. Verify each posting's account/fund/restriction combination is permissible.
3. Restricted fund posting without documented purpose match -> verdict=ESCALATE.
4. Unbalanced document -> overall_verdict=ESCALATE.
5. Posting confidence < 0.85 not human-approved -> verdict=ESCALATE.
6. Housing-related posting causing cumulative housing > parsonage_allowance_current_year -> ESCALATE with remaining budget.
7. Capitalisation: amount > capitalisation_threshold_usd mapped to operating expense (6000-8999) -> verdict=REVISE with reason 'Reclassify to fixed asset account'.
8. Aggregate: APPROVED items have no action; REVISE items have specific fix instructions; ESCALATE items go to HITL.
9. overall_verdict: APPROVED if all approved; PARTIAL if mixed; ESCALATE if any escalated.
