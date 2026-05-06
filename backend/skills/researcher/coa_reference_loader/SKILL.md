---
skill_name: coa_reference_loader
archetype: researcher
description: Load and index the church's Chart of Accounts, fund configuration, allocation schedules, capitalisation threshold, and denomination-specific accounting rules. Returns an AccountingContext.
inputs:
  - church_id
  - fiscal_year
expected_output: AccountingContext with accounts, funds, allocation_schedules, capitalisation_threshold_usd, parsonage_allowance_current_year, apportionment_accounts.
allowed_tools:
  - coa_config_tool
  - fund_config_tool
  - allocation_schedule_tool
  - denomination_rules_tool
---

# coa_reference_loader

## Workflow Steps

1. Call coa_config_tool with church_id and fiscal_year. Validate every account has a fund_id and restriction_class.
2. Call fund_config_tool. Cross-check that every fund referenced in the COA exists.
3. Call allocation_schedule_tool to retrieve facility/ministry cost allocation schedules.
4. Call denomination_rules_tool with the denomination_type. Load apportionment percentages, mandatory expense sequencing, housing allowance limits, capital threshold.
5. Assemble AccountingContext sorted by account_number ascending.
6. Flag orphaned accounts, accounts in inactive funds, missing restriction class assignments.
7. If COA not configured, return error 'COA configuration required before invoice processing' with setup_url.
