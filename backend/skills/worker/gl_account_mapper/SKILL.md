---
skill_name: gl_account_mapper
archetype: worker
description: Map each classified line item to one or more General Ledger accounts and funds, computing split allocations where required. Returns draft debit and credit posting lines with confidence scores.
inputs:
  - classified_line_items
  - accounting_context
  - allocation_override
expected_output: DraftLineAllocations with postings, total_debits, total_credits, balanced flag.
allowed_tools:
  - skill_load_tool
  - gl_account_search_tool
  - allocation_calc_tool
  - coa_semantic_search_tool
---

# gl_account_mapper

## Workflow Steps

1. For each classified line, check allocation_override first; if present use those splits with confidence=1.0.
2. Single fund eligible -> map directly. Multiple eligible + is_split_required -> apply allocation_schedule. No schedule -> requires_hitl=true with tentative 100% general-fund placeholder.
3. Use coa_semantic_search_tool to resolve best-fit GL account number within eligible fund(s).
4. Capitalised items map to fixed-asset 9000 range with memo 'Pending asset record creation'.
5. Housing-related items map to clergy housing/parsonage 5100 sub-account; memo 'Housing allowance — verify against annual resolution'.
6. Missions pass-through: map to restricted fund disbursement account; credit corresponding missions fund liability.
7. Apportionments: map to denomination assessment account + payable account; no fund split.
8. Compute split via allocation_calc_tool; sum to line total to the cent. Apply rounding residual to largest split.
9. Compute double-entry: AP invoice = debit expense/asset, credit Accounts Payable (2000).
10. Verify total_debits == total_credits per line and per document. If unbalanced flag entire document and set requires_hitl=true on all postings.
