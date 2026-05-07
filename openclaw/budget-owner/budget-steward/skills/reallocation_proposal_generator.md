# Reallocation Proposal Generator Skill

**Member:** Budget Steward (Budget Owner's Cabinet)  
**Domain:** Reallocation analysis, GL source identification, feasibility scoring  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

When GL line is running low on budget, surface reallocation options from adjacent GL accounts with surplus. Rank by relationship (same ministry preferred) and feasibility. Draft formal request for Budget Owner to send to Finance Committee.

## Input

```json
{
  "deficit_gl": "4-1300",
  "deficit_amount": 1500,
  "available_gls": [
    {
      "account_id": "4-1400",
      "name": "Outreach",
      "remaining": 1600,
      "discretionary": true,
      "same_ministry": true
    }
  ]
}
```

## Output

```json
{
  "proposal": {
    "source_gl": "4-1400",
    "amount": 1500,
    "destination_gl": "4-1300",
    "impact_source": "Outreach drops from 65% to 50%",
    "feasibility": 0.85
  },
  "formal_letter": "..."
}
```

## Algorithm

```python
async def generate_reallocation_proposal(
    church_id: str,
    deficit_gl: str,
    deficit_amount: float
) -> dict:
    """Generate reallocation proposal."""
    
    # Find GL accounts with surplus
    all_gls = load_gl_accounts(church_id)
    surplus_gls = [
        gl for gl in all_gls 
        if gl["remaining"] >= deficit_amount
    ]
    
    # Rank by feasibility
    for gl in surplus_gls:
        # Same ministry preferred
        same_ministry_score = 0.7 if is_same_ministry(deficit_gl, gl) else 0.3
        
        # Discretionary preferred
        discretionary_score = 0.3 if gl.get("discretionary") else 0.1
        
        # Low pct_spent preferred
        pct_spent = gl["ytd_spend"] / gl["annual_budget"]
        low_spend_score = 1.0 - pct_spent
        
        feasibility = (same_ministry_score * 0.5) + (discretionary_score * 0.3) + (low_spend_score * 0.2)
        gl["feasibility"] = feasibility
    
    surplus_gls.sort(key=lambda x: x["feasibility"], reverse=True)
    
    # Top choice
    if surplus_gls:
        source = surplus_gls[0]
        proposal = {
            "source_gl": source["account_id"],
            "source_gl_name": source["name"],
            "destination_gl": deficit_gl,
            "amount": deficit_amount,
            "impact_source": compose_impact(source, deficit_amount),
            "feasibility": source["feasibility"],
            "rationale": compose_rationale(source, deficit_gl)
        }
        
        # Draft formal letter
        letter = compose_reallocation_letter(proposal)
        
        return {
            "proposal": proposal,
            "formal_letter": letter,
            "alternatives": [
                {
                    "source_gl": gl["account_id"],
                    "feasibility": gl["feasibility"]
                }
                for gl in surplus_gls[1:3]
            ]
        }
    else:
        return {"proposal": None, "reason": "No GL accounts with sufficient surplus"}
```

## Execution

**Triggered by:** Budget Steward when GL reaches 90% threshold

**Action authority:** Propose; Budget Owner reviews and sends to Finance Committee

## Example Output

```
REALLOCATION PROPOSAL

Situation:
Music budget is at 90% ($9,000 / $10,000).
You have $1,000 remaining; typical monthly spend is $2,300.
You'll need additional funding or a reallocation.

Proposed Source: Outreach Discretionary (4-1400)
├─ Current: 65% spent ($6,500 / $10,000)
├─ Available: $3,500
├─ Proposed transfer: $1,500
└─ After transfer: 50% spent

Impact: Outreach becomes less flexible, but has ample cushion.

Formal Letter (for Finance Committee):
[Ready to send]
```

## Testing

- GL approaching limit → identifies surplus GL ✓
- Same ministry preference applied ✓
- Formal letter drafted for Finance Committee ✓
- Alternatives listed ✓

