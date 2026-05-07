# Vendor Risk Assessment Skill

**Member:** Queue Guardian (Treasurer's Cabinet)  
**Domain:** Vendor history analysis, escalation pattern detection, risk scoring  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Analyze vendor's 12-month history. Surface patterns: escalation rate (high = >15%), account variance (do they always use same GL?), unusual amounts. Flag vendors with >3 escalations in 6 months as high-risk.

## Input

**Vendor from invoice:**
```json
{
  "vendor_id": "VENDOR-084",
  "vendor_name": "Contractor Services Corp",
  "current_invoice_amount": 1200
}
```

## Output

**Vendor risk profile:**
```json
{
  "vendor_id": "VENDOR-084",
  "vendor_name": "Contractor Services Corp",
  "escalation_count_6m": 4,
  "escalation_rate": 0.40,
  "account_variance": 0.25,
  "risk_level": "high",
  "risk_score": 0.72,
  "flags": [
    "high_escalation_rate",
    "repeat_offender_6m"
  ]
}
```

## Algorithm

```python
async def assess_vendor_risk(
    church_id: str,
    vendor_id: str,
    months_back: int = 12
) -> dict:
    """Analyze vendor history and assess risk."""
    
    # Load vendor history
    history = load_vendor_history(church_id, vendor_id, months_back)
    
    if not history:
        return {"vendor_id": vendor_id, "risk_level": "unknown", "risk_score": 0.0}
    
    # Escalation rate
    total_invoices = len(history)
    escalations = sum(1 for inv in history if inv.get("escalated"))
    escalation_rate = (escalations / total_invoices) if total_invoices > 0 else 0
    
    # Account variance: do they use different GL codes?
    gl_codes = [inv.get("gl_code") for inv in history]
    unique_gls = len(set(gl_codes))
    variance_score = unique_gls / total_invoices  # 1.0 = one GL per invoice; >0.5 = diverse
    
    # Escalations in past 6 months
    six_months_ago = date.today() - timedelta(days=180)
    recent_escalations = sum(
        1 for inv in history 
        if inv.get("escalated") and datetime.fromisoformat(inv["date"]) > six_months_ago
    )
    
    # Risk scoring
    risk_score = 0.0
    flags = []
    
    if escalation_rate > 0.15:
        risk_score += 0.3
        flags.append("high_escalation_rate")
    
    if variance_score > 0.10:
        risk_score += 0.15
        flags.append("account_variance")
    
    if recent_escalations > 3:
        risk_score += 0.3
        flags.append("repeat_offender_6m")
    
    # Determine risk level
    if risk_score >= 0.6:
        risk_level = "high"
    elif risk_score >= 0.3:
        risk_level = "medium"
    else:
        risk_level = "low"
    
    return {
        "vendor_id": vendor_id,
        "vendor_name": history[0].get("vendor_name") if history else "Unknown",
        "total_invoices": total_invoices,
        "escalation_count": escalations,
        "escalation_rate": escalation_rate,
        "escalation_count_6m": recent_escalations,
        "account_variance": variance_score,
        "risk_level": risk_level,
        "risk_score": min(1.0, risk_score),
        "flags": flags
    }
```

## Execution

**Triggered by:** hitl_escalation event, on-demand vendor inquiry, weekly vendor risk reporter

**Action authority:** Flag vendor, alert Queue Guardian, escalate if high-risk

## Example Output

```
VENDOR RISK ASSESSMENT — Contractor Services Corp

Risk Profile:
├─ Total Invoices (12 mo): 10
├─ Escalations: 4 (40% rate)
├─ Escalations (6 mo): 4 (repeat offender)
├─ Account Variance: 25% (mostly one GL, some variance)
└─ Risk Score: 0.72 (HIGH)

Flags:
├─ 🚨 High escalation rate (40% vs. 5% church average)
├─ 🚨 Repeat offender (4 escalations in 6 months)
└─ ⚠️ Account coding variance (60% to GL A, 40% to GL B)

Pattern Analysis:
Contractor X escalates frequently. Prior escalations involved GL account confusion
(contractor codes work differently than our chart). Consider flagging their invoices
for Finance Staff GL confirmation before classification.

Recommendation: Monitor closely. Good contractor but needs oversight on GL codes.
```

## Testing

- Vendor with 40% escalation rate → flagged as high ✓
- Vendor with 4 escalations in 6 months → repeat offender flag ✓
- Vendor with diverse GL usage → variance flag ✓
- Low-risk vendor (<5% escalation) → no flags ✓

