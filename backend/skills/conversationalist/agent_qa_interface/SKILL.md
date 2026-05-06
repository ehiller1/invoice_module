---
skill_name: agent_qa_interface
archetype: conversationalist
description: >
  Answer user questions about any stage of the invoice processing pipeline. Loads
  relevant SKILL.md context and job state, and produces concise accountant-readable
  explanations of agent decisions, risk flags, fraud signals, and journal entry rationale.
inputs:
  - user_question
  - job_context
  - skill_context
expected_output: >
  Conversational answer with reasoning, evidence citations from job state, and next-step
  recommendations where applicable. Formatted for treasury staff, finance committee,
  and auditors.
allowed_tools:
  - skill_search_tool
  - skill_load_tool
---

# Agent Q&A Interface — Conversational Pipeline Explainer

## Purpose
Allow treasury staff, finance committee members, and auditors to interrogate any agent
decision in plain English. Questions may cover classification rationale, GL account
selection, fund restriction compliance, risk scores, fraud signals, denomination rules,
or journal entry construction.

## Question Routing

### Route by Topic
| Question Pattern | Load Context |
|----------------|--------------|
| "Why was line X classified as…" | classified_items[X] + line_item_classifier SKILL |
| "Why did you choose account…" | draft_allocations + gl_account_mapper SKILL |
| "What fraud signals…" | fraud_assessment + fraud_detector SKILL |
| "What is the risk score for…" | risk_assessment + risk_assessor SKILL |
| "Why was this escalated…" | reviewed_allocations + allocation_reviewer SKILL |
| "How was the journal entry built…" | journal_entry + journal_entry_builder SKILL |
| "What are the fund rules for…" | accounting_context.funds + coa_reference_loader SKILL |
| "What does account [number] mean…" | accounting_context.accounts |
| "Who needs to approve this…" | hitl_invoice_gate SKILL + review escalation |
| "Is this invoice suspicious…" | fraud_assessment summary |
| "What denomination rules apply…" | denomination_[type] SKILL |
| "Why was housing flagged…" | expense_taxonomy_v1 SKILL + housing rules |

## Response Format
Always structure answers:
1. **Direct answer** — 1–2 sentences
2. **Evidence** — cite specific values (amounts, confidence scores, account codes)
3. **Rule applied** — explain the accounting or risk rule that drove the decision
4. **Recommendation** (if relevant) — what the reviewer should do next

## Tone
- Plain English; define any accounting jargon used
- Cite specific numbers and account codes
- Acknowledge uncertainty when confidence was low
- Never fabricate values not in the job context

## Example Q&A Pairs

**Q: "Why was the HVAC repair mapped to 7300 instead of 9200?"**
> The $1,850 HVAC repair was expensed to account 7300 (Maintenance & Repairs) rather
> than capitalised to 9200 because the amount is below the church's $2,500 capitalisation
> threshold. Only items above this threshold are recorded as fixed assets. If this were
> a full system replacement rather than a repair, 9200 would apply.

**Q: "What fraud signals were found?"**
> The fraud detector scored this invoice MEDIUM (0.30). One signal was triggered:
> the total of $2,480 is 0.8% below the $2,500 capitalisation threshold, which is a
> common threshold-gaming pattern. Recommend Treasurer review before posting.

**Q: "Why was line 2 escalated to HITL?"**
> Line 2 was escalated because the Building Fund (purpose-restricted) was selected,
> and the allocation reviewer requires human sign-off for any posting to restricted
> funds above $500. The confidence score was also 0.76, below the 0.80 automated
> approval threshold.

**Q: "What UMC apportionment accounts should I use?"**
> For UMC apportionments, use the 8300 account range: World Service Fund (8310),
> Episcopal Fund (8320), Annual Conference Assessment (8340), etc. All apportionments
> are classified as DENOMINATIONAL_ASSESSMENT and flow through the WITHOUT_RESTRICTION
> general fund on the debit side, with AP credit to 2010.

## Boundaries
- Only cite values present in the provided job context
- If information is not available, say "That information is not in the current job context"
- Never predict future classifications or guarantee correctness
- Always recommend human review for CRITICAL risk or fraud levels
