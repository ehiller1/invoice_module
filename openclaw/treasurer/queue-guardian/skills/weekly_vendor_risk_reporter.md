# Weekly Vendor Risk Reporter Skill

**Member:** Queue Guardian (Treasurer's Cabinet)  
**Domain:** Vendor pattern analysis, trend detection, policy implications  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Analyze vendor patterns over past 4 weeks. Surface escalation trends, repeat offenders, policy recommendations. Identify vendors trending up (escalations increasing week-over-week) and flag for possible policy review with Finance Committee.

## Input

**Weekly vendor summary:**
```json
{
  "period": "Week of April 30 - May 7",
  "vendor_escalations": [
    {
      "vendor_id": "V-001",
      "vendor_name": "Contractor X",
      "escalations_this_week": 2,
      "escalations_last_week": 1,
      "escalations_6m": 4
    }
  ]
}
```

## Output

**Vendor risk report (email):**
```
Subject: [Cabinet] Vendor Risk Report — Week of May 7, 2024

Vendor Escalation Summary:

TRENDING UP (Investigate):
├─ Contractor X: 2 escalations this week (was 1 last week) — 4 in past 6 months
│  └─ Trend: Increasing. Consider policy review.
└─ Office Vendor Y: 1 escalation (new pattern emerging)

REPEAT OFFENDERS (Monitor):
├─ Contractor Q: 4 escalations in 6 months (40% rate)
│  └─ Recommendation: Consider re-contracting or policy change
└─ Vendor Z: 3 escalations in 6 months (30% rate)

SUMMARY:
Church average escalation rate: 5% (1 per 20 invoices)
Contractor X rate: 40% (well above average)
Vendor Q rate: 40% (well above average)

Recommendation for Finance Committee:
Review vendor policies for Contractor X and Vendor Q.
Current escalation rates suggest either vendor process issues or need for clearer guidelines.
```

## Algorithm

```python
async def generate_vendor_risk_report(
    church_id: str,
    period_weeks: int = 4
) -> str:
    """Generate weekly vendor risk report."""
    
    # Load escalation data for past N weeks
    week_end = date.today()
    week_start = week_end - timedelta(weeks=period_weeks)
    
    escalations = load_escalations(church_id, week_start, week_end)
    
    # Trend detection: compare week-over-week for each vendor
    trending = {}
    for esc in escalations:
        vendor = esc["vendor_id"]
        week_num = esc["week_number"]
        
        if vendor not in trending:
            trending[vendor] = []
        trending[vendor].append({"week": week_num, "escalations": esc["count"]})
    
    # Identify trending up, trending down, stable
    trends = {}
    for vendor, history in trending.items():
        if len(history) >= 2:
            current = history[-1]["escalations"]
            previous = history[-2]["escalations"]
            
            if current > previous:
                trends[vendor] = {"direction": "up", "change": current - previous}
            elif current < previous:
                trends[vendor] = {"direction": "down", "change": previous - current}
            else:
                trends[vendor] = {"direction": "stable", "change": 0}
    
    # Identify repeat offenders (>3 escalations in 6 months)
    all_6m_escalations = load_escalations(church_id, week_end - timedelta(days=180), week_end)
    repeat_offenders = {}
    vendor_counts = {}
    
    for esc in all_6m_escalations:
        vendor = esc["vendor_id"]
        vendor_counts[vendor] = vendor_counts.get(vendor, 0) + esc["count"]
    
    repeat_offenders = {v: count for v, count in vendor_counts.items() if count >= 3}
    
    # Compose report
    subject = f"[Cabinet] Vendor Risk Report — Week of {week_end}"
    body = compose_vendor_report_body(
        trending_vendors=trends,
        repeat_offenders=repeat_offenders,
        church_average_rate=compute_church_average_rate(all_6m_escalations)
    )
    
    return {"subject": subject, "body": body}
```

## Execution

**Triggered by:** Scheduled Friday at 5 PM

**Action authority:** Generate and send report to Treasurer and Finance Committee

## Testing

- Vendor escalation rate trending up week-over-week → identified ✓
- Repeat offender (>3 in 6 months) → flagged ✓
- Church average vs. individual vendor rate comparison ✓
- Policy implications highlighted ✓

