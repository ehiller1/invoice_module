---
skill_name: journal_entry_builder
archetype: worker
description: Assemble the final validated posting lines into a formal journal entry draft ready for ledger import. Applies fund-level sub-ledger coding, period lock checks, and generates the human-readable audit trail.
inputs:
  - reviewed_allocations
  - hitl_decisions
  - invoice_document
  - accounting_context
expected_output: JournalEntry with entry_id, lines[], total_debits, total_credits, balanced, audit_trail_url, status.
allowed_tools:
  - skill_load_tool
  - period_lock_checker_tool
  - journal_entry_schema_validator
  - audit_trail_generator_tool
---

# journal_entry_builder

## Workflow Steps

1. Call period_lock_checker_tool with invoice_date. If locked, post to first open date with warning.
2. Merge APPROVED + REVISE-resolved lines with HITL override postings. REJECTed lines excluded and logged.
3. Sequence postings: debits first (sorted by account_number), credits second.
4. Apply fund sub-ledger coding: account_number + fund_id form fully-qualified ledger code.
5. Verify total_debits == total_credits. If not, status=DRAFT and add critical warning.
6. Call audit_trail_generator_tool to produce a human-readable PDF: original invoice, agent intermediate output, classification rationale, HITL decisions, final posting. Set audit_trail_url.
7. Set status: auto-approved -> PENDING_APPROVAL; HITL collected -> PENDING_APPROVAL; any rejection -> DRAFT.
