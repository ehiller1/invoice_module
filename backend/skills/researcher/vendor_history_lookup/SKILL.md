---
skill_name: vendor_history_lookup
archetype: researcher
description: Query the last 12 months of postings for a vendor to establish the historical mapping prior. Used by line_item_classifier to raise confidence on ambiguous descriptions.
inputs:
  - church_id
  - vendor_name
  - lookback_months
expected_output: Array of {invoice_date, account_number, fund_id, amount, expense_category} sorted recency desc.
allowed_tools:
  - vendor_history_db_tool
---

# vendor_history_lookup

## Workflow Steps

1. Normalise vendor_name (strip suffixes, lowercase).
2. Query last 12 months of postings for this church + vendor combination.
3. Return up to 5 most recent. Empty array if no history.
