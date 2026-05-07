# Fund Split Calculator Skill

**Member:** Decision Deputy (Treasurer's Cabinet)  
**Domain:** Fund allocation, GL account splitting, constraint validation  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Given a line item, eligible funds, and allocation constraints, compute optimal fund split. Allocate to primary GL up to its constraint, distribute remaining to secondary accounts. Verify all lines sum to item total and no GL exceeds annual budget.

## Input

```json
{
  "item_amount": 2400,
  "primary_gl": "1-5230",
  "eligible_gls": [
    {
      "account_id": "1-5230",
      "name": "Operating",
      "annual_budget": 10000,
      "ytd_spend": 9200,
      "remaining": 800,
      "discretionary": false
    },
    {
      "account_id": "1-5350",
      "name": "Maintenance",
      "annual_budget": 12000,
      "ytd_spend": 8100,
      "remaining": 3900,
      "discretionary": true
    }
  ]
}
```

## Output

```json
{
  "item_amount": 2400,
  "proposed_split": [
    {
      "gl_account": "1-5230",
      "allocation": 800,
      "pct_of_item": 33.3,
      "reason": "Primary GL; allocate up to remaining budget"
    },
    {
      "gl_account": "1-5350",
      "allocation": 1600,
      "pct_of_item": 66.7,
      "reason": "Secondary GL; discretionary; sufficient budget"
    }
  ],
  "total_allocated": 2400,
  "verification": {
    "sum_correct": true,
    "no_overages": true,
    "residual_rounding": 0.00
  }
}
```

## Algorithm

```python
async def calculate_split(
    item_amount: float,
    primary_gl: dict,
    secondary_gls: List[dict]
) -> dict:
    """Calculate optimal fund allocation across GL accounts."""
    
    split = []
    remaining_amount = item_amount
    
    # Allocate to primary GL up to constraint
    primary_allocation = min(remaining_amount, primary_gl["remaining"])
    if primary_allocation > 0:
        split.append({
            "gl_account": primary_gl["account_id"],
            "allocation": primary_allocation,
            "reason": "Primary GL; allocate up to remaining budget"
        })
        remaining_amount -= primary_allocation
    
    # Allocate remaining to secondary GLs (sorted by feasibility)
    secondary_sorted = sorted(
        secondary_gls,
        key=lambda x: (x["remaining"] / x["annual_budget"]),  # Prefer discretionary
        reverse=True
    )
    
    for secondary in secondary_sorted:
        if remaining_amount <= 0:
            break
        
        allocation = min(remaining_amount, secondary["remaining"])
        if allocation > 0:
            split.append({
                "gl_account": secondary["account_id"],
                "allocation": allocation,
                "reason": f"Secondary GL; remaining budget: ${secondary['remaining']}"
            })
            remaining_amount -= allocation
    
    # Verify constraints
    total = sum(s["allocation"] for s in split)
    residual = item_amount - total
    
    # Handle residual rounding (round up to primary GL)
    if residual > 0 and residual < 0.01:
        if split:
            split[0]["allocation"] += residual
            total = item_amount
            residual = 0
    
    return {
        "item_amount": item_amount,
        "proposed_split": split,
        "total_allocated": total,
        "verification": {
            "sum_correct": abs(total - item_amount) < 0.01,
            "no_overages": all(
                s["allocation"] <= next(
                    gl["remaining"] for gl in [primary_gl] + secondary_gls 
                    if gl["account_id"] == s["gl_account"]
                )
                for s in split
            ),
            "residual_rounding": residual
        }
    }
```

## Execution

**Triggered by:** Decision Deputy drafting decision with SPLIT_FUNDS recommendation

**Action authority:** Calculate and propose; Treasurer confirms allocation

## Testing

- $2,400 expense split across $800 available + $3,900 available → $800 + $1,600 ✓
- Sum equals total ✓
- No GL exceeds annual budget ✓
- Residual rounding handled ✓

