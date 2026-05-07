# Field Validator Skill

**Member:** Intake Specialist (Finance Staff's Cabinet)  
**Domain:** Field format validation, date parsing, amount validation  
**Model:** claude-haiku-4-5-20251001  

## Purpose

Validate presence and format of required fields. Flag malformed amounts, unparseable dates, invalid invoice numbers. Return field-by-field validation results with errors.

## Input

**Fields to validate:**
```json
{
  "invoice_number": "INV-2024-123",
  "invoice_date": "2026-05-01",
  "vendor_name": "Office Depot",
  "amount": "245.67",
  "due_date": "2026-05-31"
}
```

## Output

**Validation Report:**
```json
{
  "valid": true,
  "field_results": {
    "invoice_number": {"valid": true, "value": "INV-2024-123"},
    "invoice_date": {"valid": true, "value": "2026-05-01", "parsed_as": "May 1, 2026"},
    "amount": {"valid": true, "value": 245.67, "currency": "USD"},
    "vendor_name": {"valid": true, "value": "Office Depot"},
    "due_date": {"valid": true, "value": "2026-05-31"}
  }
}
```

## Algorithm

```python
async def validate_fields(extracted_invoice: dict) -> dict:
    """Validate format of all required fields."""
    
    results = {}
    
    # Invoice number: non-empty string
    invoice_num = extracted_invoice.get("invoice_number", "").strip()
    results["invoice_number"] = {
        "valid": len(invoice_num) > 0,
        "value": invoice_num,
        "error": "Invoice number is empty" if not invoice_num else None,
    }
    
    # Date: valid ISO format
    for date_field in ["invoice_date", "due_date"]:
        date_str = extracted_invoice.get(date_field, "")
        try:
            parsed_date = datetime.fromisoformat(date_str)
            results[date_field] = {
                "valid": True,
                "value": date_str,
                "parsed_as": parsed_date.strftime("%B %d, %Y"),
            }
        except:
            results[date_field] = {
                "valid": False,
                "value": date_str,
                "error": "Could not parse date; expected ISO format (YYYY-MM-DD)",
            }
    
    # Amount: valid number, >0
    amount_str = extracted_invoice.get("amount", "")
    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError("Amount must be positive")
        results["amount"] = {
            "valid": True,
            "value": amount,
            "currency": "USD",
        }
    except:
        results["amount"] = {
            "valid": False,
            "value": amount_str,
            "error": "Could not parse amount; expected number (e.g., 245.67)",
        }
    
    # Vendor name: non-empty string
    vendor_name = extracted_invoice.get("vendor_name", "").strip()
    results["vendor_name"] = {
        "valid": len(vendor_name) > 0,
        "value": vendor_name,
        "error": "Vendor name is empty" if not vendor_name else None,
    }
    
    return {
        "valid": all(r["valid"] for r in results.values()),
        "field_results": results,
    }
```

## Execution

**Triggered by:** document_intake_screening (field validation step)

**Action authority:** Validate and flag errors for Finance Staff

## Example Output

```
FIELD VALIDATION — INV-2024-123

✓ ALL FIELDS VALID

Field-by-Field Results:
├─ Invoice Number: ✓ Valid (INV-2024-123)
├─ Invoice Date: ✓ Valid (May 1, 2026)
├─ Due Date: ✓ Valid (May 31, 2026)
├─ Vendor Name: ✓ Valid (Office Depot)
├─ Amount: ✓ Valid ($245.67)
└─ Line Items: ✓ Valid (3 items summing to $245.67)

NEXT STEP: Ready for GL classification
```

## Testing

- Valid date in ISO format: pass ✓
- Malformed date (e.g., "05/01/2026"): flag with suggestion ✓
- Negative amount: fail ✓
- Empty vendor name: fail ✓
- All fields valid: pass ✓

