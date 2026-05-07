# Queue Monitoring Skill

**Member:** Queue Guardian (Treasurer's Cabinet)  
**Domain:** Real-time queue monitoring, stall detection, status aggregation  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Monitor the approval queue in real-time, consuming approval_deadline_pressure and hitl_escalation events from EIME mesh. Detect stalled items (>5 business days unreviewed), compute queue metrics, and surface status summaries to help the Treasurer stay ahead of backlogs.

## Input

**Approval queue from EIME:**
```json
{
  "pending_items": [
    {
      "item_id": "INV-2024-156",
      "status": "PENDING_TREASURER_REVIEW",
      "days_pending": 6,
      "submitted_date": "2024-04-30",
      "vendor_name": "Contractor Services Corp",
      "amount": 2400,
      "assigned_approver": "treasurer@holycomeforter.org"
    }
  ]
}
```

## Output

**Queue Summary:**
```json
{
  "pending_count": 8,
  "pending_by_status": {
    "PENDING_FINANCE_STAFF": 2,
    "PENDING_BUDGET_OWNER": 3,
    "PENDING_TREASURER_REVIEW": 2,
    "PENDING_COMMITTEE": 1
  },
  "stalled_items": [
    {
      "item_id": "INV-2024-156",
      "days_pending": 6,
      "assigned_to": "treasurer@holycomeforter.org",
      "reason_for_review": "fund_restriction_conflict"
    }
  ],
  "stalled_count": 1,
  "stalled_threshold_days": 5,
  "age_distribution": {
    "1_to_3_days": 3,
    "3_to_5_days": 2,
    "over_5_days": 1
  }
}
```

## Algorithm

### Queue Status Aggregation

```python
async def monitor_queue(church_id: str) -> dict:
    """Monitor approval queue and detect stalls."""
    
    # Load all pending items
    pending = load_pending_items(church_id)
    
    # Group by status
    pending_by_status = {}
    for item in pending:
        status = item.get("status")
        if status not in pending_by_status:
            pending_by_status[status] = []
        pending_by_status[status].append(item)
    
    # Detect stalled items (>5 business days)
    today = date.today()
    stalled = []
    age_dist = {"1_to_3_days": 0, "3_to_5_days": 0, "over_5_days": 0}
    
    for item in pending:
        submitted = datetime.fromisoformat(item["submitted_date"])
        business_days = count_business_days(submitted, today)
        
        if business_days > 5:
            stalled.append({
                "item_id": item["item_id"],
                "days_pending": business_days,
                "assigned_to": item.get("assigned_approver"),
                "reason_for_review": analyze_review_reason(item)
            })
        
        # Age distribution
        if business_days <= 3:
            age_dist["1_to_3_days"] += 1
        elif business_days <= 5:
            age_dist["3_to_5_days"] += 1
        else:
            age_dist["over_5_days"] += 1
    
    return {
        "pending_count": len(pending),
        "pending_by_status": {k: len(v) for k, v in pending_by_status.items()},
        "stalled_items": stalled,
        "stalled_count": len(stalled),
        "stalled_threshold_days": 5,
        "age_distribution": age_dist
    }
```

## Execution

**Triggered by:** approval_deadline_pressure event (real-time), hourly refresh, on-demand

**Action authority:** Report status, alert on stalls, escalate to Treasurer

## Example Output

```
QUEUE STATUS — 10:30 AM

Queue Summary:
├─ Total Pending: 8 items
├─ Finance Staff review: 2 items
├─ Budget Owner approval: 3 items
├─ Treasurer decision: 2 items
└─ Committee: 1 item

Age Distribution:
├─ Fresh (1-3 days): 3 items
├─ Aging (3-5 days): 2 items
└─ STALLED (>5 days): 1 item

🚨 STALLED ITEM ALERT:
├─ INV-2024-156 ($2,400) — 6 days pending
├─ Assigned to: Treasurer
├─ Reason: Fund restriction conflict needs treasurer judgment
└─ Action: Escalate to Queue Guardian for Decision Deputy routing
```

## Testing

- Monitor queue with 10 pending items; detect 2 that are >5 days overdue ✓
- Alert when item moves from 4 days to 5+ days ✓
- Clear alert when Treasurer approves stalled item ✓
- Hourly refresh maintains accurate business day count ✓

