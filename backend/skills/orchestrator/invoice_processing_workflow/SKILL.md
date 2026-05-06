---
skill_name: invoice_processing_workflow
archetype: orchestrator
description: Top-level execution plan for processing a single invoice through the full EIME pipeline.
inputs:
  - pdf_path
  - church_id
  - document_type
expected_output: ExecutionPlan (array of steps with archetype, skill_name, inputs, depends_on)
allowed_tools:
  - skill_search_tool
  - skill_registry_tool
---

# invoice_processing_workflow

## Workflow Steps

1. Discover available skills via skill_search_tool filtered by archetype.
2. Build the canonical pipeline: pdf_extraction → coa_reference_loader (parallel) → line_item_classifier → gl_account_mapper → allocation_reviewer → (conditional) hitl_invoice_gate → journal_entry_builder → accounting_domain_distillation.
3. For each step emit ExecutionPlanStep(archetype, skill_name, inputs, depends_on).
4. Return the typed plan to the Flow layer.
