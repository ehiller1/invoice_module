# GL Budget Monitor Skill

**Member:** Budget Steward (Budget Owner's Cabinet)  
**Domain:** Budget tracking, GL line monitoring, threshold detection  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Monitor assigned GL lines for the Budget Owner. Track YTD spend, remaining budget, threshold status. Update in real-time as invoices post. Alert when line reaches 90% or 100% of budget.

## Input

```json
{
  "church_id": "HC001",
  "gl_account": "4-1300",
  "gl_name": "Music",
  "annual_budget": 10000,
  "fiscal_year_start": "2024-01-01"
}
```

## Output

```json
{
  "gl_account": "4-1300",
  "gl_name": "Music",
  "annual_budget": 10000,
  "ytd_spend": 8500,
  "remaining_budget": 1500,
  "pct_spent": 85,
  "threshold_status": "amber",
  "alert_triggered": true,
  "last_updated": "2024-08-28T14:30:00Z"
}
```

## Algorithm

```python
async def monitor_gl_budget(
    church_id: str,
    gl_account: str,
    today: date
) -> dict:
    """Monitor GL line budget status."""
    
    # Get GL configuration
    gl = load_gl_account(church_id, gl_account)
    
    # Sum all posted journal entries for this GL in fiscal year
    fiscal_year = get_fiscal_year(today)
    ytd_spend = sum_journal_entries(
        church_id,
        gl_account,
        fiscal_year_start=fiscal_year["start"],
        fiscal_year_end=today
    )
    
    annual_budget = gl["annual_budget"]
    remaining = annual_budget - ytd_spend
    pct_spent = (ytd_spend / annual_budget * 100) if annual_budget > 0 else 0
    
    # Determine threshold status
    if pct_spent < 80:
        threshold_status = "green"
        alert_triggered = False
    elif pct_spent < 95:
        threshold_status = "amber"
        alert_triggered = (pct_spent >= 90)  # Alert at 90%
    else:
        threshold_status = "red"
        alert_triggered = True  # Alert if exceeded
    
    return {
        "gl_account": gl_account,
        "gl_name": gl["name"],
        "annual_budget": annual_budget,
        "ytd_spend": ytd_spend,
        "remaining_budget": remaining,
        "pct_spent": pct_spent,
        "threshold_status": threshold_status,
        "alert_triggered": alert_triggered,
        "last_updated": datetime.now().isoformat()
    }
```

## Execution

**Triggered by:** journal_entry_ready events (real-time), daily batch at 8 AM

**Action authority:** Monitor and alert

## Example Output

```
GL Budget Status — GL 4-1300 (Music)

├─ Annual Budget: $10,000
├─ YTD Spend: $8,500 (85%)
├─ Remaining: $1,500
└─ Status: 🟡 AMBER (approaching threshold)

Alert: Budget line reaching 90%. Consider reallocation or amendment.
```

## Testing

- GL at 85% spent → amber status ✓
- Alert triggered at 90% ✓
- Real-time update on journal posting ✓
- Multiple GL lines tracked independently ✓

