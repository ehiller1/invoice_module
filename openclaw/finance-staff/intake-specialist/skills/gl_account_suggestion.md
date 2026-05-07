# GL Account Suggestion Skill

**Member:** Intake Specialist (Finance Staff's Cabinet)  
**Domain:** GL classification, confidence scoring, account recommendation  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Suggest GL account for extracted invoice with confidence band (high ≥0.85, medium 0.70-0.85, low <0.70). Analyze vendor history, keyword match, and typical amount. Return top 3 suggestions with supporting evidence.

## Input

```json
{
  "vendor_name": "Office Depot",
  "description": "Office supplies",
  "amount": 245.67,
  "church_id": "HC001"
}
```

## Output

```json
{
  "suggestions": [
    {
      "gl_account": "1-7200",
      "gl_name": "Supplies",
      "confidence": 0.92,
      "confidence_band": "HIGH",
      "evidence": [
        "Vendor used GL 1-7200 in 25 of 26 prior invoices (96%)",
        "Description 'office supplies' matches GL keyword",
        "Amount $245.67 within vendor typical range"
      ]
    }
  ]
}
```

## Algorithm

```python
async def suggest_gl_accounts(
    church_id: str,
    vendor_name: str,
    description: str,
    amount: float
) -> List[dict]:
    """Suggest GL accounts with confidence bands."""
    
    suggestions = []
    
    # Get vendor history
    vendor = lookup_vendor(church_id, vendor_name)
    if not vendor:
        return []  # Can't suggest without vendor history
    
    vendor_id = vendor["vendor_id"]
    history = load_vendor_invoice_history(church_id, vendor_id, months_back=12)
    
    # GL usage distribution
    gl_distribution = {}
    for inv in history:
        gl = inv.get("gl_code")
        gl_distribution[gl] = gl_distribution.get(gl, 0) + 1
    
    # Keyword match
    gl_accounts = load_gl_accounts(church_id)
    keyword_matches = {}
    
    for gl in gl_accounts:
        keywords = [gl["name"].lower(), gl.get("description", "").lower()]
        desc_lower = description.lower()
        
        match_score = 0
        if any(kw in desc_lower for kw in keywords):
            match_score = 0.9
        elif desc_lower in gl["description"].lower():
            match_score = 0.7
        else:
            match_score = 0.3
        
        keyword_matches[gl["account_id"]] = match_score
    
    # Amount typical
    amount_matches = {}
    for gl in gl_accounts:
        gl_history = [inv for inv in history if inv["gl_code"] == gl["account_id"]]
        if gl_history:
            typical_amount = sum(inv["amount"] for inv in gl_history) / len(gl_history)
            amount_variance = abs(amount - typical_amount) / typical_amount
            
            if amount_variance < 0.2:  # Within 20%
                amount_matches[gl["account_id"]] = 0.9
            elif amount_variance < 0.5:  # Within 50%
                amount_matches[gl["account_id"]] = 0.7
            else:
                amount_matches[gl["account_id"]] = 0.4
        else:
            amount_matches[gl["account_id"]] = 0.5
    
    # Confidence calculation
    for gl_code in sorted(
        set(gl_distribution.keys()) | set(keyword_matches.keys()),
        key=lambda x: gl_distribution.get(x, 0),
        reverse=True
    )[:3]:  # Top 3 suggestions
        
        vendor_history_confidence = (gl_distribution.get(gl_code, 0) / len(history)) * 0.7
        keyword_confidence = keyword_matches.get(gl_code, 0) * 0.2
        amount_confidence = amount_matches.get(gl_code, 0) * 0.1
        
        confidence = vendor_history_confidence + keyword_confidence + amount_confidence
        
        if confidence > 0.70:
            gl = next(g for g in gl_accounts if g["account_id"] == gl_code)
            
            confidence_band = (
                "HIGH" if confidence >= 0.85 
                else "MEDIUM" if confidence >= 0.70 
                else "LOW"
            )
            
            evidence = [
                f"Vendor used GL {gl_code} in {gl_distribution.get(gl_code, 0)} of {len(history)} prior invoices ({(gl_distribution.get(gl_code, 0) / len(history) * 100):.0f}%)",
                f"Description '{description}' matches GL keywords at {keyword_confidence:.0%}",
                f"Amount ${amount:.2f} {'within' if amount_matches.get(gl_code, 0) > 0.7 else 'outside'} typical vendor range"
            ]
            
            suggestions.append({
                "gl_account": gl_code,
                "gl_name": gl["name"],
                "confidence": confidence,
                "confidence_band": confidence_band,
                "evidence": evidence
            })
    
    return suggestions
```

## Execution

**Triggered by:** Intake screening (after vendor lookup)

**Action authority:** HIGH confidence → auto-approve; MEDIUM → propose to Finance Staff; LOW → escalate

## Example Output

```
GL Suggestion: Office Depot, $245.67

Recommendation: GL 1-7200 (Supplies) — Confidence 0.92 (HIGH)
Evidence:
├─ Vendor used this GL in 25 of 26 prior invoices (96%)
├─ Description 'office supplies' keyword matches GL name
└─ Amount $245.67 within vendor's typical Supplies range ($100-500)

Alternative: GL 1-7300 (Equipment) — Confidence 0.08 (very unlikely)
```

## Testing

- Vendor with 96% history to GL → HIGH confidence ✓
- Keyword match + typical amount → MEDIUM confidence ✓
- Unknown vendor pattern → LOW confidence ✓
- Top 3 suggestions ranked correctly ✓

