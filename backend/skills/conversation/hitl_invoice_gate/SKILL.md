---
skill_name: hitl_invoice_gate
archetype: conversationalist
description: Present escalated or ambiguous invoice line items to a human reviewer via a structured review interface. Collect fund split decisions, account overrides, and approval notes.
inputs:
  - escalation_items
  - draft_allocations
  - accounting_context
  - invoice_document
expected_output: HITLDecisions with line_decisions[] and all_resolved flag.
allowed_tools:
  - skill_load_tool
  - embark_review_ui_tool
  - notification_tool
---

# hitl_invoice_gate

## Workflow Steps

1. Identify reviewer role: restricted fund > $500 -> Finance Committee. Parsonage/housing -> Executive Pastor or Personnel Committee. Otherwise -> Treasurer.
2. Send in-app notification with invoice number, vendor, total, deep link.
3. Render structured review card: line description, vendor amount, tentative posting, rationale, escalation reason.
4. Present fund split options with current balances and restriction class. Percentages must sum to 100%.
5. Missions pass-through items require attestation checkbox: 'I confirm this payment has been approved by the Missions Committee'.
6. Housing items: show YTD utilisation and remaining budget.
7. Validate override postings balance (debits = credits).
8. Reject items: include reviewer notes for rejection report.
9. Return HITLDecisions to Flow for resumption of journal_entry_builder.
