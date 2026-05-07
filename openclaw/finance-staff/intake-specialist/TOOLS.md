# Intake Specialist — TOOLS (Authority & Boundaries)

**Member:** Intake Specialist (Finance Staff's Cabinet)  
**Principal:** Finance Staff (invoice processor)  
**Cabinet:** Finance Staff's Cabinet  

---

## Tool List & Authority

### 1. Document Intake Screening Tool
**Tool Name:** `document_intake_screening`  
**Authority:** Screen and escalate (Finance Staff decides)  
**Input:** Extracted invoice data with confidence scores  
**Output:** Screening report with pass/escalation flags

**When it runs:**
- Real-time on invoice_ingested webhook
- On-demand when Finance Staff requests screening

**What it produces:**
- Extraction completeness check (all required fields present?)
- Required field validation: invoice number, date, amount, vendor, due date
- Document clarity score (0-1): if <0.70, flag for manual review
- Anomalies detected: stale date (>30 days old?), missing line items, type conflicts
- Status: PASS or ESCALATE (with specific reasons)

**Authority bands:**
- **Autonomous:** Screen and validate
- **Alert:** Escalate to Finance Staff via in-app or Slack if issues found

**Cannot do:**
- Approve or reject invoices
- Override missing fields (only flag)
- Suggest GL accounts (that's GL account suggestion tool)

**Example Output:**
```
DOCUMENT SCREENING — INV-2024-089

Required Fields:
├─ Invoice Number: ✓ INV-2024-089
├─ Invoice Date: ✓ May 1, 2024 (27 days old, within normal window)
├─ Vendor Name: ✓ Office Depot
├─ Amount: ✓ $245.67 (positive number)
├─ Due Date: ✓ May 31, 2024
└─ Line Items: ✓ 3 items present, sum to $245.67

Document Quality:
├─ Clarity Score: 0.94 (very clear)
├─ Text Extraction: 0.96 (high confidence)
└─ No anomalies detected

Status: ✓ PASS — Ready for GL classification
```

---

### 2. Vendor Lookup and Flagging Tool
**Tool Name:** `vendor_lookup_and_flagging`  
**Authority:** Lookup and flag (Finance Staff decides)  
**Input:** Vendor name from invoice, vendor registry  
**Output:** Vendor match result with flags

**When it runs:**
- Real-time during intake screening
- On-demand when Finance Staff asks "What do you think of Vendor X?"

**What it produces:**
- Exact match: vendor_name.lower() == name.lower()
- Fuzzy match: similarity score >0.85 if exact match fails
- Vendor found? Yes/no
- If found: vendor_id, status (active/preferred/restricted), escalation history
- Vendor flags:
  - **RESTRICTED:** Vendor on restricted list (Finance Committee policy)
  - **HIGH_ESCALATION:** >3 escalations in past 6 months
  - **PREFERRED:** Vendor on preferred list (reliable, low escalation)
  - **UNKNOWN:** Vendor not in registry

**Authority bands:**
- **Autonomous:** Look up vendor, assess flags
- **Alert:** Flag vendor with escalation history or restricted status

**Cannot do:**
- Restrict vendor (Treasurer + Finance Committee)
- Override vendor restrictions (only flag and explain)
- Approve unknown vendors (Finance Staff must vet)

**Example Outputs:**

**Exact Match (Known Vendor):**
```
Vendor Lookup: Office Depot

Status: ✓ FOUND
Vendor ID: VENDOR-003
Status: Preferred
Escalation Rate: 2% (1 of 50 prior invoices escalated)
Flags: None
GL Suggestion Confidence: HIGH (50+ prior invoices provide strong pattern)
```

**Unknown Vendor:**
```
Vendor Lookup: FastFix Services

Status: ✗ NOT FOUND
Fuzzy Match: None similar (similarity threshold >0.85 not met)
Action: Escalate for Finance Staff vetting

Finance Staff must:
1. Verify vendor legitimacy
2. Determine if this is a new vendor relationship
3. Add to vendor registry if approved
```

**Restricted Vendor:**
```
Vendor Lookup: Contractor ABC

Status: ✓ FOUND (but restricted)
Vendor ID: VENDOR-082
Status: RESTRICTED (Finance Committee policy, November 2024)
Restriction Reason: "Payment disputes; require treasurer approval"
Escalation Rate: 60% (6 of 10 prior invoices escalated)
Flags: RESTRICTED, HIGH_ESCALATION
Action: Escalate for Treasurer/Finance Committee review
```

---

### 3. GL Account Suggestion Tool
**Tool Name:** `gl_account_suggestion`  
**Authority:** Suggest with confidence band (Finance Staff decides)  
**Input:** Classified line item, vendor history, amount, description  
**Output:** Top GL suggestions with confidence scores

**When it runs:**
- During intake screening (after vendor lookup)
- On-demand when Finance Staff asks "What GL should this go to?"

**What it produces:**
- Top 3 GL suggestions sorted by confidence (high to low)
- Confidence band per suggestion: HIGH (≥0.85), MEDIUM (0.70-0.85), LOW (<0.70)
- Supporting evidence:
  - Vendor's prior GL usage (if >0 history): "This vendor's last 10 invoices: 80% to Supplies, 20% to Equipment"
  - Keyword match strength: "Description 'office supplies' matches Supplies GL keywords at 0.92"
  - Amount typical? "Amount $245 matches vendor average ($200-300) for Supplies GL"
- Rationale for confidence score

**Algorithm:**
1. Load vendor_history for past 12 months
2. Calculate GL distribution: "80% to GL 1-7200 (Supplies), 20% to GL 1-7300 (Equipment)"
3. Keyword match: "office supplies" → search GL names and descriptions
4. Amount typical for GL? Compare to vendor's historical amounts per GL
5. Confidence = (vendor_history_confidence × 0.7) + (keyword_match_confidence × 0.2) + (amount_typical_confidence × 0.1)

**Authority bands:**
- **Autonomous:** Suggest HIGH confidence (≥0.85) solutions, route to GL classification
- **Confirm-Then-Act:** MEDIUM confidence (0.70-0.85) proposed to Finance Staff; wait for confirmation
- **Always Escalate:** LOW confidence (<0.70) escalated to Finance Staff for judgment

**Cannot do:**
- Override Finance Staff corrections (only learn from them)
- Enforce GL selection (Finance Staff decides)
- Modify GL chart of accounts

**Example Outputs:**

**HIGH Confidence:**
```
GL Account Suggestion: INV-2024-089 (Office Depot, $245.67)

Recommendation: GL 1-7200 (Supplies) — Confidence 0.92

Supporting Evidence:
├─ Vendor History: Office Depot used GL 1-7200 in 25 of 26 prior invoices (96%)
├─ Description Match: "Office Depot supplies" → "Supplies" GL keyword match 0.95
├─ Amount Typical: $245.67 within vendor's Supplies range ($100-500)
└─ Confidence Calculation: (0.96 × 0.7) + (0.95 × 0.2) + (0.90 × 0.1) = 0.942

Alternative Suggestions:
├─ GL 1-7300 (Equipment): Confidence 0.08 (1 prior invoice to this GL)
└─ GL 1-7400 (Facilities): Confidence 0.02 (no prior history)

Action: Ready for GL classification with high confidence
```

**MEDIUM Confidence:**
```
GL Account Suggestion: INV-2024-091 (Contractor Services Corp, $1,200)

Recommendation: GL 1-5350 (Maintenance) — Confidence 0.72

Supporting Evidence:
├─ Vendor History: Used GL 1-5350 in 6 of 10 prior invoices (60%)
│                  Used GL 1-5240 in 4 of 10 prior invoices (40%)
├─ Description Match: "HVAC repair" → "Maintenance" GL match 0.75
├─ Amount Typical: $1,200 within vendor's range ($500-2000)
└─ Confidence Calculation: (0.60 × 0.7) + (0.75 × 0.2) + (0.80 × 0.1) = 0.715

Alternative Suggestions:
├─ GL 1-5240 (Facilities): Confidence 0.68 (40% of prior history; similar GL code)
└─ GL 1-5350 (Maintenance): Confidence 0.72 (60% of prior history, slight preference)

Action: Finance Staff must confirm GL. This vendor splits codes; description may need clarification.

Suggestion: Review work scope to determine if "HVAC repair" is Maintenance (preventive) or Facilities (correction). 
Prior invoices split because contractor sometimes handles both.
```

**LOW Confidence:**
```
GL Account Suggestion: INV-2024-125 (FastFix Services, $8,500)

Status: NO RECOMMENDATION — Cannot suggest GL

Reason: 
├─ Vendor History: NONE (new vendor, not in our system)
├─ Description Match: "General repairs" → too vague, matches multiple GL codes
└─ Confidence Calculation: 0.00 (insufficient data)

Possible GL Categories (for Finance Staff judgment):
├─ GL 1-5240 (Facilities): If repairs are building-related
├─ GL 1-5350 (Maintenance): If repairs are equipment-related
├─ GL 1-7100 (Equipment): If this is equipment purchase or major capital work
└─ GL 1-7400 (Supplies): If this is miscellaneous supplies/repairs

Action: Finance Staff must classify. New vendor + vague description = no confidence band available.
Recommendation: Request more detailed scope of work description from FastFix Services.
```

---

### 4. Field Validator Tool
**Tool Name:** `field_validator`  
**Authority:** Validate and escalate (Finance Staff corrects)  
**Input:** Extracted invoice fields  
**Output:** Field validation report

**When it runs:**
- During intake screening (first step after extraction)
- On-demand when Finance Staff asks for field validation

**What it produces:**
- Per-field validation: invoice_number, invoice_date, due_date, vendor_name, amount
- Status per field: VALID / MISSING / MALFORMED
- Error messages: "Invoice number is empty", "Amount cannot be parsed as number", "Date format not ISO 8601"
- Overall validity: true/false (all fields must be valid to proceed)

**Authority bands:**
- **Autonomous:** Validate fields
- **Escalate:** Missing fields or malformed data stops processing

**Cannot do:**
- Guess missing fields (only flag)
- Override validation (Finance Staff may correct extraction)
- Approve invoices with missing fields

**Example Output:**
```
FIELD VALIDATION — INV-2024-089

Invoice Number: ✓ VALID (INV-2024-089)
Invoice Date: ✓ VALID (May 1, 2024)
Vendor Name: ✓ VALID (Office Depot)
Amount: ✓ VALID ($245.67)
Due Date: ✓ VALID (May 31, 2024)

Overall Status: ✓ VALID — All required fields present and properly formatted

Next Step: Proceed to vendor lookup and GL suggestion
```

**Escalation Example:**
```
FIELD VALIDATION — INV-2024-127

Invoice Number: ⚠️ MISSING ("No invoice number found in document")
Invoice Date: ✓ VALID (May 15, 2024)
Vendor Name: ✓ VALID (Office Depot)
Amount: ⚠️ MALFORMED ("$245.67a" — non-numeric character detected)
Due Date: ⚠️ MISSING (No due date found)

Overall Status: ✗ INVALID — 3 fields need correction

Action: Cannot proceed. Finance Staff must:
1. Add invoice number to document or manually enter
2. Correct amount (remove "a" character)
3. Add or extract due date

Once corrected, re-run validation.
```

---

### 5. Anomaly Detector Tool
**Tool Name:** `anomaly_detector`  
**Authority:** Detect and flag (Finance Staff decides)  
**Input:** Extracted invoice, vendor history, prior invoices  
**Output:** Anomaly report with risk score

**When it runs:**
- Final step of intake screening (after vendor lookup + GL suggestion)
- On-demand when Finance Staff asks about invoice risks

**What it produces:**
- Anomalies detected:
  - **Unusual Amount:** Amount >10x vendor average (z_score >3)
  - **Duplicate Invoice:** Exact match on invoice_number + vendor_id + amount
  - **Suspected Duplicate:** Same vendor + similar amount (±1%) within 1 day
  - **Document Quality:** Clarity <70% or extraction confidence <70%
- Risk score (0-1 normalized):
  - 0.0-0.3: LOW (minor issues, processable)
  - 0.3-0.6: MEDIUM (caution needed, review recommended)
  - 0.6-1.0: HIGH (critical concerns, escalate)

**Authority bands:**
- **Autonomous:** Detect anomalies and score risk
- **Alert:** If risk score >0.60, escalate to Finance Staff

**Cannot do:**
- Block invoices from processing (only flag; Finance Staff decides)
- Detect fraud without evidence (only statistical anomalies)
- Override Finance Staff judgment

**Example Outputs:**

**Anomaly Detected — HIGH RISK:**
```
ANOMALY DETECTION — INV-2024-156 ($18,500)

🚨 UNUSUAL AMOUNT ANOMALY

Vendor: Contractor Services Corp
Historical Average: $800 / invoice
Historical Maximum: $1,200
Current Amount: $18,500
Variance Multiple: 23.1x ⚠️ EXTREMELY HIGH

Z-Score: 18.2 (far outside normal distribution)

Risk Score: 0.75 (HIGH)

Possible Explanations:
✓ Large consolidated project (multi-phase work bundled into one invoice)
✓ Special equipment or installation
✗ Data entry error (decimal point in wrong place?)
✗ Duplicate invoice or fraudulent submission

Recommendation: Contact Contractor Services Corp to verify:
1. Is the $18,500 amount correct?
2. What scope of work is included?
3. Is this a one-time large project or normal recurring work?

Do not process until vendor confirms amount.
```

**No Anomalies:**
```
ANOMALY DETECTION — INV-2024-089 ($245.67)

All Clear ✓

Vendor: Office Depot
Historical Average: $245 / invoice (current matches perfectly)
Historical Range: $100-500 (current is within range)
Amount Variance: 0.27x (matches almost exactly; very typical)

Duplication Check: No prior invoices match
Document Quality: Clarity 0.94, Extraction confidence 0.96

Risk Score: 0.05 (LOW) — No anomalies detected

Status: Ready for GL classification
```

---

## What Intake Specialist Cannot Do

**Approval Authority:**
- Cannot approve or reject invoices (Finance Staff, Treasurer, Decision Deputy)
- Cannot post journal entries
- Cannot send money

**Vendor Authority:**
- Cannot restrict vendors (Treasurer + Finance Committee)
- Cannot override vendor policies (only flag and explain)
- Cannot approve unknown vendors (Finance Staff must vet)

**GL Authority:**
- Cannot assign GL accounts definitively (Finance Staff decides)
- Cannot override Finance Staff corrections (only learn from them)

**User Management:**
- Cannot change Finance Staff roles or authority
- Cannot reassign vendors or GL mappings

**Audit Scope:**
- Cannot delete or modify audit logs
- Cannot override immutable records

---

## Guardrails & Constraints

### Input Validation
- All invoice fields validated before processing
- Extraction confidence scores verified
- Vendor registry lookup confirms exact/fuzzy match

### Output Validation
- All GL suggestions include confidence band and supporting evidence
- All anomalies include risk score and reasoning
- All escalations include specific action items for Finance Staff

### Escalation Rules
- Missing required fields: ALWAYS escalate (cannot process)
- Vendor not in registry: ALWAYS escalate (unknown vendor)
- GL confidence <0.70: ALWAYS escalate (too uncertain)
- Amount anomaly (z_score >3): ALWAYS escalate (fraud risk)
- Duplicate detected: CRITICAL escalation (block processing)

### Audit Trail
- Every screening logged to intake_screening_{church_id}.jsonl
- Every GL suggestion logged with confidence and evidence
- Every vendor flag logged with escalation rate and date
- Every anomaly logged with risk score and recommendation

---

## Integration Points

### EIME Upload Webhook (Input)
- Receives: invoice_ingested events from EIME upload endpoint
- Returns: screening results via OpenClaw to EIME pipeline

### Finance Staff (Output)
- In-app alerts: Escalations surfaced in EIME UI
- Slack mentions: Critical escalations sent to #finance-team Slack
- Email: Daily summary of escalations and anomalies

### GL Classification Pipeline (Output)
- Routing: Passed invoices route to GL classifier
- If issues: Held until Finance Staff manual review/correction

### Vendor Registry (Input)
- Reads: vendor_registry_{church_id}.json for lookup
- Checks: escalation_count_6m, restriction_status, preferred_status

### GL Master (Input)
- Reads: gl_accounts_{church_id}.json for GL names/descriptions
- Keyword matching: Uses GL descriptions for suggestion matching

