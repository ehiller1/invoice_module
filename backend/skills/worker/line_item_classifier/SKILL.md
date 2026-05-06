---
skill_name: line_item_classifier
archetype: worker
description: Classify each extracted invoice line item by expense category, ministry area, fund eligibility, and special flags (housing, missions pass-through, capitalise, apportionment).
inputs:
  - line_items
  - accounting_context
  - vendor_history
expected_output: ClassifiedLineItems[] with line_id, expense_category, ministry_area, fund_eligibility, flags, classification_rationale, confidence.
allowed_tools:
  - skill_load_tool
  - skill_resource_tool
  - vendor_history_tool
  - coa_semantic_search_tool
---

# line_item_classifier

## Workflow Steps

1. For each line item, load the expense taxonomy and use coa_semantic_search_tool to find candidate categories.
2. If vendor_history is non-empty, check the most recent 5 postings as a prior on ambiguous descriptions (raises confidence by 10+ pts per FR-03.5).
3. Determine expense_category. If confidence < 0.80, set requires_hitl=true.
4. Determine ministry_area via keyword + memo override.
5. Check capitalise flag: amount > capitalisation_threshold_usd AND category in {Equipment, Improvement, Technology}.
6. Check is_housing_related: vendor on parsonage list OR description matches housing keywords. Validate against parsonage_allowance budget.
7. Check is_missions_passthrough: vendor is registered missionary org AND payment designated in memo. Forces requires_hitl=true.
8. Check is_apportionment: vendor is denominational body AND maps to apportionment account.
9. Determine fund_eligibility: intersect candidate funds with accounting_context.funds. If multiple eligible and is_split_required not set, set requires_hitl=true.
10. Write plain-English classification_rationale.
