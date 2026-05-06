---
skill_name: accounting_domain_distillation
archetype: membrane
description: Package the completed JournalEntry for emission to the Embark Accounting ledger domain. Enforces the domain boundary - validates completeness, strips internal agent reasoning artifacts, emits the AccountingDomainEvent.
inputs:
  - journal_entry
  - source_domain
expected_output: AccountingDomainEvent envelope with event_type=JOURNAL_ENTRY_READY, payload, metadata.
allowed_tools:
  - skill_load_tool
  - domain_event_emitter_tool
  - completeness_validator_tool
---

# accounting_domain_distillation

## Workflow Steps

1. Call completeness_validator_tool: verify entry_id, church_id, fiscal_year, accounting_period, balanced=true, >=1 debit + >=1 credit, audit_trail_url populated.
2. If unbalanced or missing required, do NOT emit. Return error.
3. Strip internal reasoning fields (classification_rationale, confidence scores, intermediate workflow states) from the payload. They remain in the audit trail PDF only.
4. Construct AccountingDomainEvent envelope with event_type=JOURNAL_ENTRY_READY.
5. Call domain_event_emitter_tool to publish to accounting.journal_entries topic.
6. Return the emitted event envelope to the Flow for confirmation logging.
