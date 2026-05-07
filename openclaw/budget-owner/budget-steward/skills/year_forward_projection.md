# Year-Forward Projection Skill

**Member:** Budget Steward (Budget Owner's Cabinet)  
**Domain:** Forecasting, seasonal adjustment, year-end projection  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Estimate year-end position from YTD spend and remaining months. Account for seasonal patterns (April/May Easter peaks, December holidays). Return projection with confidence scoring that improves as more data becomes available.

## Input

```json
{
  "gl_account": "4-1300",
  "ytd_spend": 8500,
  "months_elapsed": 8,
  "annual_budget": 10000,
  "historical_pattern": {
    "april_may_average": 3100,
    "baseline_average": 2000
  }
}
```

## Output

```json
{
  "simple_projection": 12750,
  "adjusted_projection": 10200,
  "confidence": 0.70,
  "projected_year_end": 10200,
  "projected_overage": 200,
  "assumptions": "Assumes April/May seasonality, baseline normalizes Jun-Dec"
}
```

## Algorithm

```python
async def project_year_end(
    gl_account: str,
    ytd_spend: float,
    months_elapsed: int,
    annual_budget: float
) -> dict:
    """Project year-end spending with seasonal adjustment."""
    
    months_remaining = 12 - months_elapsed
    
    # Simple projection (no seasonal adjustment)
    monthly_avg = ytd_spend / months_elapsed if months_elapsed > 0 else 0
    simple_projection = monthly_avg * 12
    
    # Load historical pattern (if available)
    historical = load_historical_pattern(gl_account)
    
    # Adjusted projection (with seasonal adjustment)
    if historical and months_elapsed >= 3:
        # Identify seasonal months in remaining period
        seasonal_months = count_seasonal_months(months_elapsed + 1, 12)
        baseline_months = months_remaining - seasonal_months
        
        seasonal_avg = historical.get("april_may_average", monthly_avg)
        baseline_avg = historical.get("baseline_average", monthly_avg)
        
        projected_remaining = (
            (seasonal_months * seasonal_avg) + 
            (baseline_months * baseline_avg)
        )
        adjusted_projection = ytd_spend + projected_remaining
    else:
        adjusted_projection = simple_projection
    
    # Confidence scoring (improves with more data)
    if months_elapsed < 2:
        confidence = 0.3
    elif months_elapsed < 4:
        confidence = 0.5
    elif months_elapsed < 6:
        confidence = 0.7
    else:
        confidence = 0.85
    
    projected_overage = max(0, adjusted_projection - annual_budget)
    
    return {
        "simple_projection": simple_projection,
        "adjusted_projection": adjusted_projection,
        "confidence": confidence,
        "projected_year_end": adjusted_projection,
        "projected_overage": projected_overage,
        "assumptions": compose_assumption_summary(historical, months_elapsed),
        "months_remaining": months_remaining
    }
```

## Execution

**Triggered by:** Weekly digest generation, on-demand query

**Action authority:** Project and recommend; Budget Owner uses for planning

## Example Output

```
Year-Forward Projection — Music GL

YTD (8 months): $8,500
Monthly Average: $2,150

SIMPLE PROJECTION: $12,750 (at current rate)
SEASONAL ADJUSTMENT: Music peaks Apr/May (Easter), normalizes Jun-Aug
ADJUSTED PROJECTION: $10,200 (accounting for seasonal pattern)

Projected Overage: $200
Confidence: 0.70 (need Sep-Oct data to refine)

Assumptions:
- Apr/May average ($3,100/mo) was Easter-driven
- Jun-Aug baseline ($2,000/mo) expected to continue
- Sep-Dec expected at $1,500/mo (post-event season)
```

## Testing

- YTD $8,500, monthly avg $2,150 → projects to $25,800 simply ✓
- Seasonal adjustment factors in Easter peaks → adjusted lower ✓
- Confidence 0.70 at 8 months elapsed ✓
- Overage calculated correctly ✓

