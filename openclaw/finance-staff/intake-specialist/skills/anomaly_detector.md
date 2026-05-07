# Anomaly Detector Skill

**Member:** Intake Specialist (Finance Staff's Cabinet)  
**Domain:** Outlier detection, invoice pattern analysis, fraud risk scoring  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Detect unusual patterns: amount significantly higher than vendor history, document quality issues, extraction confidence below threshold, duplicate invoices. Return anomaly report with risk score (0-1).

## Input

**Extracted invoice + vendor history:**
```json
{
  "invoice_ref": "INV-2024-124",
  "vendor_name": "Contractor Services Corp",
  "vendor_id": "VENDOR-001",
  "amount": 18500,
  "description": "Facilities maintenance",
  "extraction_confidence": 0.92,
  "document_clarity": 0.78,
  "vendor_historical_avg_amount": 800,
  "vendor_historical_max_amount": 1200
}
```

## Output

**Anomaly Report:**
```json
{
  "anomalies_detected": 1,
  "anomalies": [
    {
      "type": "unusual_amount",
      "severity": "high",
      "amount": 18500,
      "vendor_avg": 800,
      "variance_multiple": 23.1,
      "message": "Invoice amount ($18,500) is 23x vendor historical average ($800)",
      "recommendation": "Contact vendor to confirm amount is correct"
    }
  ],
  "risk_score": 0.75
}
```

## Algorithm

### 1. Amount Anomaly Detection

```python
async def detect_amount_anomaly(
    amount: float,
    vendor_id: str,
    church_id: str
) -> dict:
    """Check if amount is unusual for this vendor."""
    
    vendor_history = load_vendor_history(church_id, vendor_id, months=12)
    
    if not vendor_history:
        return None  # No historical data
    
    historical_amounts = [inv["amount"] for inv in vendor_history]
    avg_amount = sum(historical_amounts) / len(historical_amounts)
    max_amount = max(historical_amounts)
    std_dev = calculate_std_dev(historical_amounts)
    
    # Check if amount is an outlier (>3 std devs from mean)
    z_score = (amount - avg_amount) / std_dev if std_dev > 0 else 0
    
    if z_score > 3:
        return {
            "type": "unusual_amount",
            "severity": "high" if amount > max_amount * 5 else "medium",
            "amount": amount,
            "vendor_avg": avg_amount,
            "vendor_max": max_amount,
            "variance_multiple": amount / avg_amount if avg_amount > 0 else float("inf"),
            "z_score": z_score,
            "message": f"Invoice amount (${amount:.2f}) is {(amount / avg_amount):.0f}x vendor average (${avg_amount:.2f})",
            "recommendation": "Contact vendor to verify amount is correct",
        }
    
    return None
```

### 2. Duplicate Detection

```python
async def detect_duplicate(
    invoice_number: str,
    vendor_id: str,
    amount: float,
    church_id: str
) -> dict:
    """Check if this invoice has already been processed."""
    
    # Exact match
    prior = load_invoice(
        church_id=church_id,
        invoice_number=invoice_number,
        vendor_id=vendor_id,
    )
    
    if prior:
        return {
            "type": "duplicate_invoice",
            "severity": "critical",
            "invoice_number": invoice_number,
            "prior_invoice_id": prior["id"],
            "prior_upload_date": prior["uploaded_at"],
            "message": f"Invoice {invoice_number} from {vendor_id} was previously uploaded on {prior['uploaded_at']}",
            "recommendation": "Do not process; mark as duplicate",
        }
    
    # Fuzzy match: same vendor + similar amount within 1 day
    recent_similar = load_invoices(
        church_id=church_id,
        vendor_id=vendor_id,
        amount_range=(amount * 0.99, amount * 1.01),
        days_back=1,
    )
    
    if recent_similar:
        return {
            "type": "suspected_duplicate",
            "severity": "warning",
            "invoice_number": invoice_number,
            "similar_invoices": [inv["invoice_number"] for inv in recent_similar],
            "message": f"Similar invoice from same vendor uploaded within past day",
            "recommendation": "Verify this is not a duplicate before processing",
        }
    
    return None
```

### 3. Overall Risk Scoring

```python
async def calculate_risk_score(
    extracted_invoice: dict,
    anomalies: List[dict]
) -> float:
    """
    Combine multiple risk factors into 0-1 score.
    
    Risk factors:
    - Extraction confidence <70%
    - Document clarity <70%
    - Amount anomaly (high severity)
    - Suspected duplicate
    """
    
    risk_score = 0.0
    
    # Extraction confidence
    confidence = extracted_invoice.get("extraction_confidence", 0.9)
    if confidence < 0.70:
        risk_score += 0.3
    elif confidence < 0.85:
        risk_score += 0.15
    
    # Document clarity
    clarity = extracted_invoice.get("document_clarity", 0.9)
    if clarity < 0.70:
        risk_score += 0.2
    
    # Anomalies
    for anomaly in anomalies:
        if anomaly["severity"] == "critical":
            risk_score += 0.5
        elif anomaly["severity"] == "high":
            risk_score += 0.25
        elif anomaly["severity"] == "medium":
            risk_score += 0.1
    
    return min(1.0, risk_score)
```

## Execution

**Triggered by:** invoice_ingested event (final validation step)

**Action authority:** Flag anomalies for Finance Staff attention; block duplicates

## Example Output

```
ANOMALY DETECTION — INV-2024-124

🚨 HIGH-RISK ANOMALY DETECTED

Unusual Amount:
├─ Invoice Amount: $18,500
├─ Vendor Historical Average: $800 (past 12 months)
├─ Variance Multiple: 23.1x (EXTREMELY HIGH)
├─ Vendor Historical Maximum: $1,200
├─ This Invoice vs. Max: 15.4x higher
└─ Risk Level: 🔴 CRITICAL

ANALYSIS:
This contractor typically invoices $500–$1,500 per job.
An $18,500 invoice from the same vendor is highly unusual.

POSSIBLE EXPLANATIONS:
✓ Large project or multi-phase work that was consolidated into one invoice
✓ Special equipment purchase or installation
✓ Data entry error (decimal point in wrong place? $1,850 vs $18,500?)
✗ Duplicate invoice from system error
✗ Fraudulent invoice

RECOMMENDATION:
Contact Contractor Services Corp immediately to verify:
1. Is the $18,500 amount correct?
2. What scope of work is included?
3. Is this a one-time large project, or normal recurring work?

Do not process until vendor confirms amount.

RISK SCORE: 0.75 (HIGH)
```

## Testing

- Vendor amount 23x historical average: flag as high-risk anomaly ✓
- Exact duplicate invoice: critical flag, block processing ✓
- Document clarity <70%: warning flag ✓
- All fields normal: no anomalies detected ✓

