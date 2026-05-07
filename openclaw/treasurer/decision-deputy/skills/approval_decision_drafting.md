# Approval Decision Drafting Skill

**Member:** Decision Deputy (Treasurer's Cabinet)  
**Domain:** Decision letter composition, rationale explanation, recommendation generation  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Draft approval decision letters in the Treasurer's voice when items are escalated from Queue Guardian. Analyze escalation context (budget, fund restrictions, vendor history) and generate decision letter with clear recommendation (APPROVE / OVERRIDE / REJECT / SPLIT_FUNDS) plus 2-3 alternative paths.

## Input

**Escalation context from Queue Guardian:**
```json
{
  "item_id": "INV-2024-156",
  "amount": 2400,
  "vendor_name": "Contractor Services Corp",
  "escalation_reason": "stall",
  "budget_context": {
    "gl_line": "1-5230",
    "pct_spent": 92,
    "projected_overage": 500
  },
  "vendor_history": {
    "escalation_rate": 0.40,
    "escalation_count_6m": 4
  }
}
```

## Output

**Decision letter draft:**
```
TO: Treasurer
FROM: Decision Deputy
RE: INV-2024-156 — Contractor Services Corp ($2,400)

RECOMMENDATION: SPLIT_FUNDS

RATIONALE:
Operating budget is 92% spent ($9,200 / $10,000).
This $2,400 invoice exceeds remaining balance ($800).
However, funds are available in Maintenance Contingency GL.
Contractor is within vendor history range; escalations are unrelated to amount.

CANONICAL AUTHORITY:
No fund restrictions apply. Episcopal budget policy permits dual-GL allocation
when primary GL exceeds budget and secondary GL has surplus.

PROPOSED ALLOCATION:
GL 1-5230 (Operating): $800 (remaining balance)
GL 1-5350 (Maintenance): $1,600 (from contingency; facility work matches GL purpose)

ALTERNATIVES:
1. REALLOCATE: Move $2,400 from Music discretionary (60% spent, $1,600 available)
2. REQUEST AMENDMENT: Seek $2,400 budget amendment from Finance Committee (timeline: 2-3 weeks)
3. PHASE: Approve $1,200 now, defer $1,200 to June

What would you prefer?
```

## Algorithm

```python
async def draft_decision(
    item: dict,
    escalation_reason: str,
    budget_context: dict,
    vendor_history: dict
) -> dict:
    """Draft approval decision in Treasurer's voice."""
    
    # Analyze escalation reason
    if escalation_reason == "fund_restriction_violation":
        recommendation = "REJECT"
        recommendation_detail = "Fund restriction does not permit this expense"
    elif escalation_reason == "budget_overage":
        recommendation = "SPLIT_FUNDS or REALLOCATE"
        recommendation_detail = "Allocate across available GL lines"
    elif escalation_reason == "stall":
        recommendation = "APPROVE with conditions or ESCALATE"
        recommendation_detail = "Item is routine; recommend approval"
    else:
        recommendation = "REVIEW"
        recommendation_detail = "Escalation reason requires Treasurer judgment"
    
    # Generate alternatives based on situation
    alternatives = generate_abundance_alternatives(
        item_amount=item["amount"],
        budget_context=budget_context
    )
    
    # Compose letter
    letter = {
        "to": "Treasurer",
        "from": "Decision Deputy",
        "subject": f"INV-{item['item_id']} — {item['vendor_name']} (${item['amount']})",
        "recommendation": recommendation,
        "recommendation_detail": recommendation_detail,
        "rationale": compose_rationale(item, budget_context, vendor_history),
        "canonical_authority": look_up_canonical_authority(escalation_reason),
        "proposed_action": compose_action(recommendation, item, budget_context),
        "alternatives": alternatives,
        "next_step": "Approve, modify, or select alternative"
    }
    
    return letter
```

## Execution

**Triggered by:** Queue Guardian escalation (via OpenClaw sessions_send)

**Action authority:** Draft only; Treasurer must approve before sending to EIME

## Testing

- Stalled invoice → drafts APPROVE with rationale ✓
- Budget overage → drafts SPLIT_FUNDS with alternatives ✓
- Fund restriction violation → recommends REJECT ✓
- All decisions include canonical authority ✓

