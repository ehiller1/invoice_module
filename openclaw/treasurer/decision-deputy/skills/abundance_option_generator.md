# Abundance Option Generator Skill

**Member:** Decision Deputy (Treasurer's Cabinet)  
**Domain:** Alternative generation, reallocation analysis, budget amendment drafting  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

When budget overage is proposed, surface alternatives before recommending rejection: reallocate from GL with surplus, request budget amendment, phase expense across fiscal periods. Generate 3+ options with feasibility scoring.

## Input

```json
{
  "item_amount": 5000,
  "primary_gl": "1-5230",
  "primary_remaining": -1000,
  "other_gls": [
    {
      "account_id": "1-4300",
      "name": "Music",
      "remaining": 1600,
      "discretionary": true
    }
  ]
}
```

## Output

```json
{
  "options": [
    {
      "option": "REALLOCATE",
      "source_gl": "1-4300",
      "amount": 1600,
      "impact": "Music drops from 60% to 0% spent",
      "feasibility": 0.85
    },
    {
      "option": "AMEND",
      "amount": 1000,
      "timeline": "2-3 weeks",
      "feasibility": 0.70
    },
    {
      "option": "PHASE",
      "now": 4000,
      "defer": 1000,
      "timeline": "Defer to June",
      "feasibility": 0.95
    }
  ]
}
```

## Algorithm

```python
async def generate_abundance_options(
    item_amount: float,
    primary_gl: dict,
    all_gls: List[dict]
) -> List[dict]:
    """Generate alternative paths to approval."""
    
    options = []
    shortfall = item_amount - primary_gl["remaining"]
    
    # OPTION 1: REALLOCATE
    # Find GLs with surplus that can cover shortfall
    surplus_gls = [gl for gl in all_gls if gl["remaining"] >= shortfall]
    
    for gl in surplus_gls:
        feasibility = 0.85 if gl.get("discretionary") else 0.60
        
        options.append({
            "option": "REALLOCATE",
            "source_gl": gl["account_id"],
            "source_gl_name": gl["name"],
            "amount": shortfall,
            "impact": f"{gl['name']} would drop from {pct_spent(gl)}% to {pct_after(gl, shortfall)}%",
            "feasibility": feasibility,
            "pros": "Immediate; no amendment delay",
            "cons": "Affects another department/ministry"
        })
    
    # OPTION 2: REQUEST AMENDMENT
    options.append({
        "option": "AMENDMENT",
        "amount": shortfall,
        "timeline": "2-3 weeks (Finance Committee meeting)",
        "feasibility": 0.70,
        "pros": "Permanent budget increase; establishes precedent",
        "cons": "Requires committee approval; delays execution"
    })
    
    # OPTION 3: PHASE ACROSS PERIODS
    # Phase into next fiscal period or split across quarters
    remaining_quarters = compute_remaining_quarters()
    
    options.append({
        "option": "PHASE",
        "now": primary_gl["remaining"],
        "defer": shortfall,
        "timeline": f"Defer to next fiscal period or Q{remaining_quarters + 1}",
        "feasibility": 0.95,
        "pros": "Spreads expense across periods; highest likelihood",
        "cons": "Delays partial fulfillment; vendor may charge mobilization fee"
    })
    
    return options
```

## Execution

**Triggered by:** Decision Deputy before recommending REJECT due to budget

**Action authority:** Generate and propose alternatives; Treasurer selects path

## Testing

- Budget overage of $1,000 → 3+ options generated ✓
- Reallocate option includes feasibility scoring ✓
- Amendment includes Finance Committee timeline ✓
- Phase option scores highest feasibility ✓

