# Document Intake Screening Skill

**Member:** Intake Specialist (Finance Staff's Cabinet)  
**Domain:** Document quality assessment, extraction validation, field completeness  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Validate extraction completeness for invoices. Check that all required fields are present (invoice number, date, amount, vendor, due date). Flag anomalies (document clarity <70%, stale date >30 days old, missing line items). Return screening report.

## Input

**Extracted invoice:**
```json
{
  "invoice_number": "INV-2024-089",
  "invoice_date": "2024-05-01",
  "vendor_name": "Office Depot",
  "amount": 245.67,
  "due_date": "2024-05-31",
  "line_items": [
    {"description": "Office supplies", "amount": 245.67}
  ],
  "extraction_confidence": 0.94,
  "document_clarity": 0.94
}
```

## Output

```json
{
  "status": "PASS",
  "extraction_completeness": {
    "invoice_number": "present",
    "invoice_date": "present",
    "vendor_name": "present",
    "amount": "present",
    "due_date": "present"
  },
  "anomalies": [],
  "document_quality": {
    "clarity": 0.94,
    "extraction_confidence": 0.94
  }
}
```

## Algorithm

```python
async def screen_document_intake(
    extracted_invoice: dict,
    today: date
) -> dict:
    """Validate extraction completeness and quality."""
    
    # Required fields validation
    required_fields = {
        "invoice_number": extracted_invoice.get("invoice_number", "").strip(),
        "invoice_date": extracted_invoice.get("invoice_date", ""),
        "vendor_name": extracted_invoice.get("vendor_name", "").strip(),
        "amount": extracted_invoice.get("amount", ""),
        "due_date": extracted_invoice.get("due_date", "")
    }
    
    completeness = {}
    for field, value in required_fields.items():
        if not value:
            completeness[field] = "missing"
        else:
            completeness[field] = "present"
    
    # Check for anomalies
    anomalies = []
    
    # Stale document (>30 days old)
    try:
        inv_date = datetime.fromisoformat(extracted_invoice["invoice_date"])
        age_days = (today - inv_date.date()).days
        if age_days > 30:
            anomalies.append({
                "type": "stale_document",
                "severity": "warning",
                "age_days": age_days
            })
    except:
        pass
    
    # Missing line items
    line_items = extracted_invoice.get("line_items", [])
    if not line_items:
        anomalies.append({
            "type": "missing_line_items",
            "severity": "warning"
        })
    
    # Low document clarity
    clarity = extracted_invoice.get("document_clarity", 1.0)
    if clarity < 0.70:
        anomalies.append({
            "type": "poor_document_clarity",
            "severity": "critical",
            "clarity": clarity
        })
    
    # Low extraction confidence
    confidence = extracted_invoice.get("extraction_confidence", 1.0)
    if confidence < 0.70:
        anomalies.append({
            "type": "low_extraction_confidence",
            "severity": "critical",
            "confidence": confidence
        })
    
    # Overall status
    has_missing = any(v == "missing" for v in completeness.values())
    has_critical = any(a["severity"] == "critical" for a in anomalies)
    
    status = "FAIL" if (has_missing or has_critical) else "PASS"
    
    return {
        "status": status,
        "extraction_completeness": completeness,
        "anomalies": anomalies,
        "document_quality": {
            "clarity": clarity,
            "extraction_confidence": confidence
        }
    }
```

## Execution

**Triggered by:** invoice_ingested webhook (first step)

**Action authority:** Screen and escalate if issues found

## Example Output

```
DOCUMENT SCREENING — INV-2024-089

Required Fields:
├─ Invoice Number: ✓ Present
├─ Invoice Date: ✓ Present (May 1, 2024 — 27 days old, normal)
├─ Vendor Name: ✓ Present
├─ Amount: ✓ Present ($245.67)
├─ Due Date: ✓ Present
└─ Line Items: ✓ Present (3 items)

Document Quality:
├─ Clarity: 0.94 (Excellent)
├─ Extraction: 0.96 (High confidence)
└─ No anomalies detected

Status: ✓ PASS — Ready for GL classification
```

## Testing

- All fields present, no anomalies → PASS ✓
- Missing invoice number → FAIL ✓
- Document clarity <70% → critical, FAIL ✓
- Stale document (>30 days) → warning flag ✓

