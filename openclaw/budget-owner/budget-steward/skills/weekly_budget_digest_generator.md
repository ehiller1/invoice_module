# Weekly Budget Digest Generator Skill

**Member:** Budget Steward (Budget Owner's Cabinet)  
**Domain:** Budget briefing, pattern analysis, coaching insights  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Compose Friday 4 PM weekly budget digest: YTD spend, remaining, spending rate, projected year-end, and coaching insight (seasonal pattern, variance, trend). Deliver via email to Budget Owner.

## Input

```json
{
  "period": "Week of August 21-28",
  "gl_account": "4-1300",
  "ytd_spend": 8500,
  "weekly_spend": 750,
  "annual_budget": 10000,
  "historical_pattern": {}
}
```

## Output

```
Subject: [Cabinet] Budget Digest — Music — Week of August 28, 2024

Hello Kyle,

Your music budget for this week:

Current Status:
├─ YTD Spend: $8,500 / $10,000 (85%)
├─ Remaining: $1,500
└─ This Week: $750 (on track)

Year-Forward Projection:
├─ Current Rate: $2,150/month (including Easter peaks)
├─ Baseline (Jun-Aug): $2,000/month
├─ Projected Year-End: $10,200 (slight overage)
└─ Confidence: 70% (need Sep-Oct data)

Coaching Insight:
Your April/May spending was 3x other months (Easter events). That's expected seasonal variation.
You're spending at your normal baseline since June. Your discipline has been excellent.

No action needed unless Sep-Dec spending increases unexpectedly.

— Budget Steward
```

## Algorithm

```python
async def generate_weekly_digest(
    church_id: str,
    gl_account: str,
    budget_owner_email: str
) -> str:
    """Generate Friday afternoon budget briefing."""
    
    # Current week's data
    week_start = date.today() - timedelta(days=7)
    week_end = date.today()
    
    status = await monitor_gl_budget(church_id, gl_account, week_end)
    weekly_spend = sum_journal_entries(
        church_id, gl_account,
        date_from=week_start,
        date_to=week_end
    )
    
    # Year-forward projection
    projection = await project_year_end(
        gl_account,
        status["ytd_spend"],
        status["pct_spent"],
        status["annual_budget"]
    )
    
    # Coaching insight
    coaching = generate_coaching_insight(
        gl_account,
        status,
        projection,
        historical_pattern=load_historical_pattern(gl_account)
    )
    
    # Compose email
    subject = f"[Cabinet] Budget Digest — {status['gl_name']} — Week of {week_end}"
    
    body = f"""
Hello {get_budget_owner_name(budget_owner_email)},

Your {status['gl_name']} budget for this week:

Current Status:
├─ YTD Spend: ${status['ytd_spend']:,.0f} / ${status['annual_budget']:,.0f} ({status['pct_spent']:.0f}%)
├─ Remaining: ${status['remaining_budget']:,.0f}
└─ This Week: ${weekly_spend:,.0f}

Year-Forward Projection:
├─ Projected Year-End: ${projection['projected_year_end']:,.0f}
├─ Projected Overage: ${projection['projected_overage']:,.0f}
└─ Confidence: {projection['confidence']:.0%}

Coaching Insight:
{coaching}

— Budget Steward
"""
    
    return {"subject": subject, "to": budget_owner_email, "body": body}
```

## Execution

**Triggered by:** Scheduled Friday at 4 PM

**Action authority:** Generate and send email

## Testing

- Weekly digest includes YTD, remaining, weekly spend ✓
- Year-forward projection included ✓
- Coaching insight generated (pattern analysis) ✓
- Email sent Friday 4 PM ✓

