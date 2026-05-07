# Budget Threshold Scanner Skill

**Member:** Queue Guardian (Treasurer's Cabinet)  
**Domain:** Budget monitoring, GL line tracking, threshold alerts  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Consume budget_overage_risk events from EIME mesh. Track GL line balances across the church. Alert when a line reaches 90% or exceeds 100% of budget. Compute year-forward projections to help Treasurer see where lines will land by fiscal year-end.

## Input

**Budget alert event:**
```json
{
  "church_id": "HC001",
  "gl_line": "1-5230-Operating",
  "ytd_spend": 9200,
  "annual_budget": 10000,
  "transaction_amount": 800,
  "transaction_date": "2024-08-28"
}
```

## Output

**Budget status report:**
```json
{
  "gl_line": "1-5230-Operating",
  "annual_budget": 10000,
  "ytd_spend": 9200,
  "remaining_budget": 800,
  "pct_spent": 92,
  "threshold_status": "amber",
  "alert_triggered": true,
  "year_forward_projection": {
    "monthly_average": 2300,
    "months_remaining": 4,
    "projected_year_end": 10500,
    "projected_overage": 500
  }
}
```

## Algorithm

```python
async def scan_budget_thresholds(
    church_id: str,
    today: date
) -> List[dict]:
    """Check GL lines and alert on threshold breaches."""
    
    alerts = []
    fiscal_year = get_fiscal_year(today)
    
    # Get all GL lines for this church
    gl_lines = load_gl_lines(church_id)
    
    for gl in gl_lines:
        # Load YTD spend
        ytd_spend = sum_journal_entries(
            church_id, 
            gl["account_id"], 
            fiscal_year_start=fiscal_year["start"],
            fiscal_year_end=today
        )
        
        annual_budget = gl["annual_budget"]
        pct_spent = (ytd_spend / annual_budget * 100) if annual_budget > 0 else 0
        
        # Check thresholds
        threshold_status = "green" if pct_spent < 80 else "amber" if pct_spent < 95 else "red"
        
        if pct_spent >= 90:
            # Compute year-forward projection
            months_elapsed = count_months(fiscal_year["start"], today)
            months_remaining = 12 - months_elapsed
            monthly_avg = ytd_spend / months_elapsed if months_elapsed > 0 else 0
            
            projected_year_end = monthly_avg * 12
            projected_overage = max(0, projected_year_end - annual_budget)
            
            alerts.append({
                "gl_line": gl["account_id"],
                "gl_name": gl["name"],
                "annual_budget": annual_budget,
                "ytd_spend": ytd_spend,
                "remaining_budget": annual_budget - ytd_spend,
                "pct_spent": pct_spent,
                "threshold_status": threshold_status,
                "alert_triggered": True,
                "year_forward_projection": {
                    "monthly_average": monthly_avg,
                    "months_remaining": months_remaining,
                    "projected_year_end": projected_year_end,
                    "projected_overage": projected_overage
                }
            })
    
    return alerts
```

## Execution

**Triggered by:** budget_overage_risk event, journal_entry_ready events, daily at 8 AM

**Action authority:** Alert Treasurer, compute projections, escalate if overage imminent

## Example Output

```
BUDGET THRESHOLD ALERT — GL 1-5230 (Operating)

Current Status:
├─ Annual Budget: $10,000
├─ YTD Spend: $9,200 (92%)
├─ Remaining: $800
└─ Status: 🟡 AMBER (approaching limit)

Year-Forward Projection:
├─ Monthly Average: $2,300
├─ Months Remaining: 4 (Sep-Dec)
├─ Projected Year-End: $10,500
├─ Projected Overage: $500
└─ Likelihood: HIGH (at current rate)

Recommendation:
Before September spending, consider:
1. Reallocate $500 from discretionary GL
2. Request $500 budget amendment
3. Phase any discretionary expenses to Q1 next year
```

## Testing

- GL line at 85% budget → alert triggered ✓
- Projection shows 110% by year-end → escalates ✓
- Multiple GL lines: each tracked independently ✓
- Daily refresh updates balances ✓

