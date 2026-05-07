# Daily Queue Digest Generator Skill

**Member:** Queue Guardian (Treasurer's Cabinet)  
**Domain:** Briefing composition, event aggregation, priority ranking  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Aggregate past 24 hours of queue events (stalls, budget alerts, vendor flags) into a morning digest email for the Treasurer. Rank action items by priority: stalled items first, budget breaches second, vendor risks third.

## Input

**24-hour event summary:**
```json
{
  "period": "2024-05-07 08:00 to 2024-05-08 08:00",
  "stalled_items": [
    {"item_id": "INV-2024-156", "days_pending": 8}
  ],
  "budget_alerts": [
    {"gl_line": "1-5230", "pct_spent": 92}
  ],
  "vendor_flags": [
    {"vendor_name": "Contractor X", "escalation_rate": 0.40}
  ]
}
```

## Output

**Email digest:**
```
Subject: [Cabinet] Queue Digest — May 8, 2024

Hello Treasurer,

Your queue digest for the past 24 hours:

🚨 ACTION ITEMS (3):

1. STALLED ITEM: INV-2024-156 ($2,400) — 8 days pending
   → Assigned to: You for decision
   → Issue: Fund restriction conflict
   → Action: Escalate to Decision Deputy? Or Approve with override?

2. BUDGET ALERT: GL 1-5230 (Operating) at 92% budget
   → Remaining: $800
   → Projected overage: $500 by year-end
   → Action: Consider reallocation or amendment before September spending

3. VENDOR FLAG: Contractor Services Corp — 40% escalation rate
   → Current invoice: $1,200 (within range)
   → Recommendation: GL coding may need your confirmation

Coaching Insight:
Your April/May spending patterns show seasonal variation. Music budget peaked
in April (Easter prep); now normalizing. Budget overages likely temporary.

—Queue Guardian
```

## Algorithm

```python
async def generate_daily_digest(
    church_id: str,
    treasurer_email: str,
    period_hours: int = 24
) -> str:
    """Generate morning briefing email."""
    
    # Load events from past N hours
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=period_hours)
    
    events = load_events(church_id, start_time, end_time)
    
    # Aggregate by type
    stalled = [e for e in events if e["type"] == "stall_alert"]
    budget_alerts = [e for e in events if e["type"] == "budget_threshold"]
    vendor_flags = [e for e in events if e["type"] == "vendor_risk_flag"]
    
    # Rank action items: stalls > breaches > risks
    action_items = []
    action_items.extend([
        {"priority": 1, "category": "stall", "content": s}
        for s in stalled
    ])
    action_items.extend([
        {"priority": 2, "category": "budget", "content": b}
        for b in budget_alerts
    ])
    action_items.extend([
        {"priority": 3, "category": "vendor", "content": v}
        for v in vendor_flags
    ])
    
    action_items.sort(key=lambda x: x["priority"])
    
    # Compose email
    subject = f"[Cabinet] Queue Digest — {end_time.strftime('%B %d, %Y')}"
    body = compose_email_body(
        church_id=church_id,
        action_items=action_items,
        period_start=start_time,
        period_end=end_time
    )
    
    return {"subject": subject, "to": treasurer_email, "body": body}
```

## Execution

**Triggered by:** Scheduled daily at 8 AM (weekdays only)

**Action authority:** Generate and send email

## Testing

- 24-hour period with 3 stalls, 2 budget alerts, 1 vendor flag → all aggregated ✓
- Stalled items ranked first, budget second, vendor risks third ✓
- Email subject includes date ✓
- Weekends skipped (weekday schedule only) ✓

