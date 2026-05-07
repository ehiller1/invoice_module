# Vendor Lookup and Flagging Skill

**Member:** Intake Specialist (Finance Staff's Cabinet)  
**Domain:** Vendor registry lookup, escalation history, restriction checking  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Check vendor against registry. Return vendor status (found/not found, preferred/restricted). Flag vendors with high escalation rate (>3 in 6 months) or on restricted list. Support Finance Staff vendor inquiry.

## Input

```json
{
  "vendor_name": "Office Depot",
  "church_id": "HC001"
}
```

## Output

```json
{
  "found": true,
  "vendor_id": "VENDOR-003",
  "vendor_name": "Office Depot",
  "status": "preferred",
  "escalation_count_6m": 1,
  "escalation_rate": 0.02,
  "flags": [],
  "risk_level": "low"
}
```

## Algorithm

```python
async def lookup_vendor(
    church_id: str,
    vendor_name: str
) -> dict:
    """Lookup vendor in registry and assess flags."""
    
    # Exact match lookup
    vendor_registry = load_vendor_registry(church_id)
    
    # Normalize for comparison
    normalized_name = vendor_name.lower().strip()
    
    exact_match = next(
        (v for v in vendor_registry 
         if v["name"].lower().strip() == normalized_name),
        None
    )
    
    if exact_match:
        vendor_id = exact_match["vendor_id"]
        status = exact_match.get("status", "active")
    else:
        # Fuzzy match
        matches = []
        for v in vendor_registry:
            similarity = compute_similarity(
                normalized_name,
                v["name"].lower().strip()
            )
            if similarity > 0.85:
                matches.append((v, similarity))
        
        if matches:
            exact_match = sorted(matches, key=lambda x: x[1], reverse=True)[0][0]
            vendor_id = exact_match["vendor_id"]
            status = exact_match.get("status", "active")
        else:
            return {
                "found": False,
                "vendor_name": vendor_name,
                "reason": "Vendor not in registry"
            }
    
    # Load escalation history
    escalation_history = load_vendor_escalations(
        church_id,
        vendor_id,
        months_back=6
    )
    
    escalations_6m = len(escalation_history)
    total_invoices = load_vendor_invoice_count(church_id, vendor_id, months_back=6)
    escalation_rate = escalations_6m / total_invoices if total_invoices > 0 else 0
    
    # Check flags
    flags = []
    if status == "restricted":
        flags.append("restricted")
    if escalations_6m >= 3:
        flags.append("high_escalation")
    if status == "preferred":
        flags.append("preferred_vendor")
    
    # Risk level
    if status == "restricted":
        risk_level = "critical"
    elif escalations_6m >= 3:
        risk_level = "high"
    elif escalation_rate > 0.15:
        risk_level = "medium"
    else:
        risk_level = "low"
    
    return {
        "found": True,
        "vendor_id": vendor_id,
        "vendor_name": exact_match["name"],
        "status": status,
        "escalation_count_6m": escalations_6m,
        "escalation_rate": escalation_rate,
        "total_invoices_6m": total_invoices,
        "flags": flags,
        "risk_level": risk_level
    }
```

## Execution

**Triggered by:** Intake screening, on-demand vendor inquiry via Slack

**Action authority:** Lookup and flag; escalate if critical status

## Example Outputs

**Preferred Vendor:**
```
Vendor: Office Depot (VENDOR-003)
Status: ✓ Preferred
Escalations: 1 of 50 (2% rate, excellent)
Flags: None
Risk: LOW
```

**High Escalation Vendor:**
```
Vendor: Contractor Services Corp (VENDOR-084)
Status: Active
Escalations: 4 of 10 (40% rate, concerning)
Flags: High escalation
Risk: MEDIUM
```

**Restricted Vendor:**
```
Vendor: Vendor X (VENDOR-999)
Status: ⛔ RESTRICTED (Finance Committee policy, Nov 2024)
Reason: Payment disputes; requires treasurer approval
Escalations: 6 of 10 (60% rate)
Risk: CRITICAL
Action: Escalate to Treasurer
```

## Testing

- Preferred vendor lookup → flags as preferred ✓
- Vendor with 4 escalations in 6m → high flag ✓
- Restricted vendor → critical flag ✓
- Unknown vendor → not found ✓

