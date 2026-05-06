# Budget Feature Testing Guide

This guide shows how to test the budget functionality using sample files for Holy Comforter Episcopal Church.

## Sample Files

### Budget File
**File:** `holy-comforter-budget-2024.csv`

A complete annual budget for Holy Comforter Episcopal Church with:
- 50 accounts covering all major expense and revenue categories
- Monthly budget columns (Jan-Dec) with consistent monthly allocation
- Annual budget totals matching 12× monthly amounts
- Realistic Episcopal church spending patterns:
  - Clergy compensation (salary, housing, CPF): $73,500 annual
  - Diocesan Assessment: $19,500 (10.8% of $180K pledge revenue)
  - Utilities: $14,400
  - Building maintenance: $12,000
  - Staff salaries: $54,000
  - Christian education & outreach: $12,600

**Key budgets for testing:**
- **Account 6600 (Utilities):** $14,400 annual ($1,200/month) — Tests normal spending
- **Account 6500 (Maintenance):** $12,000 annual ($1,000/month) — Tests over-budget scenario
- **Account 6300 (Printing):** $1,800 annual ($150/month) — Tests warning scenario
- **Account 4100 (Pledges):** $180,000 annual — Revenue account

### Sample Invoices

#### Invoice 1: Regular Operations (HC-001)
- **Amount:** $3,250
- **Accounts impacted:**
  - 6100 (Vestments): $1,200
  - 6300 (Printing): $1,250
  - 6200 (Office): $300
  - 6400 (Flowers): $500
- **Expected result:** All charges WITHIN_BUDGET for January
- **Budget status:** Account 6300 would be at ~87% of monthly budget after this invoice (WARNING level if approaching 100%)

#### Invoice 2: Maintenance Repairs (HC-002)
- **Amount:** $5,800
- **Accounts impacted:**
  - 6500 (Maintenance): $5,800 total
    - HVAC repair: $2,500
    - Roof inspection: $1,200
    - Plumbing: $800
    - Electrical: $600
    - Landscaping: $700
- **Expected result:** This invoice ALONE exceeds monthly maintenance budget of $1,000
- **Budget status:** OVER_BUDGET (580% of monthly budget)
- **Expected behavior:** 
  - Triggers HITL escalation
  - Requires human approval with budget attestation
  - Displays warning in HITL modal about maintenance overage

#### Invoice 3: Utility Bill (HC-003)
- **Amount:** $1,850
- **Accounts impacted:**
  - 6600 (Utilities): $1,850 total
    - Electricity: $1,200
    - Gas: $450
    - Water: $200
- **Expected result:** Invoice exceeds monthly utility budget of $1,200
- **Budget status:** WARNING or OVER_BUDGET depending on threshold (154% of monthly budget)
- **Expected behavior:**
  - Likely triggers escalation if over 100% of budget
  - Displays variance in HITL modal

## Testing Scenarios

### Scenario 1: Upload Budget and Verify
1. Navigate to Budget page in web UI
2. Upload `holy-comforter-budget-2024.csv`
3. Verify:
   - Budget plan loaded successfully
   - All 50 accounts parsed correctly
   - Annual totals calculated correctly
   - Dashboard shows 0% budget consumed (no invoices yet)

### Scenario 2: Process Normal Invoice (HC-001)
1. Create PDF from `sample-invoice-HC-001.json` (or upload JSON directly if system supports)
2. Process through normal invoice workflow
3. Expected result:
   - Invoice classified to correct accounts
   - Budget check shows all lines WITHIN_BUDGET
   - No HITL escalation
   - Transaction approved and emitted
   - YTD updated: 6100=+$1,200, 6300=+$1,250, 6200=+$300, 6400=+$500

### Scenario 3: Process Over-Budget Invoice (HC-002)
1. Upload `sample-invoice-HC-002.json` (Maintenance invoice)
2. Process through invoice workflow
3. Expected behavior:
   - Budget check detects account 6500 will be OVER_BUDGET
   - Line item 6500 escalated to HITL with reason: "Maintenance exceeds monthly budget by 480%"
   - HITL modal shows:
     - Account 6500
     - Monthly budget: $1,000
     - YTD before: $0
     - This invoice: $5,800
     - YTD after: $5,800
     - Status: OVER_BUDGET (480% consumed)
   - User must check "Budget Approval Attestation" checkbox before approving
4. Verify:
   - After approval, YTD updated: 6500=+$5,800
   - Dashboard now shows 58% of maintenance budget consumed for the month

### Scenario 4: Process Warning Invoice (HC-003)
1. Upload `sample-invoice-HC-003.json` (Utility bill)
2. Process through workflow
3. Expected behavior:
   - Budget check detects account 6600 is at WARNING level (154% of monthly budget)
   - Behavior depends on `budget_warning_threshold` setting:
     - If threshold is 0.80 (default): Escalates to HITL as "At Risk" or "Over Budget"
     - Can be configured to allow warnings without escalation
4. If escalated:
   - HITL shows variance: "Utilities at 154% of monthly budget"
   - User approves with attestation
5. If allowed without escalation:
   - Transaction processes normally
   - Dashboard shows warning color on utilities account

### Scenario 5: Year-to-Date Tracking
1. After processing all three invoices in sequence:
   - YTD summary shows:
     - 6100: $1,200 / $6,000 monthly (20%)
     - 6200: $300 / $200 monthly (150% — OVER)
     - 6300: $1,250 / $150 monthly (833% — OVER)
     - 6400: $500 / $200 monthly (250% — OVER)
     - 6500: $5,800 / $1,000 monthly (580% — OVER)
     - 6600: $1,850 / $1,200 monthly (154% — OVER)
2. Dashboard shows:
   - Multiple accounts in RED (over budget)
   - Overall consumption high for January
3. Variance report shows:
   - Accounts needing manager review
   - Potential budget amendment needed for maintenance

### Scenario 6: Budget Amendment
1. Maintenance issues in January required $5,800 instead of budgeted $1,000
2. Vestry approves amendment to account 6500 for February
3. Update budget file with new monthly amounts for Feb-Dec
4. Re-upload budget with `amendment_number=1`
5. System preserves original budget and notes amendment
6. YTD tracking continues with amended budget going forward

### Scenario 7: Threshold Configuration
1. Navigate to Budget page
2. Adjust warning threshold from default 0.80 to 0.90
3. Re-process a borderline invoice
4. With higher threshold (90%), some warnings that escalated at 80% now pass through
5. Verify behavior change in HITL

## API Testing (Direct)

### Test Budget Upload
```bash
curl -X POST http://localhost:8000/api/churches/holy_comforter/budget/import-spreadsheet \
  -H "Content-Type: multipart/form-data" \
  -F "file=@holy-comforter-budget-2024.csv"
```

Expected response:
```json
{
  "status": "success",
  "budget_plan": {
    "fiscal_year": 2024,
    "accounts_loaded": 50,
    "annual_total": 412200
  }
}
```

### Test Budget Retrieval
```bash
curl http://localhost:8000/api/churches/holy_comforter/budget
```

Expected response:
```json
{
  "fiscal_year": 2024,
  "plan_date": "2024-01-01",
  "amendment_number": 0,
  "accounts": {
    "6500": {"annual_budget": 12000, "monthly_budget": 1000, ...},
    "6600": {"annual_budget": 14400, "monthly_budget": 1200, ...},
    ...
  }
}
```

### Test Variance Report
```bash
curl http://localhost:8000/api/churches/holy_comforter/budget/variance-report
```

Expected response shows YTD vs budget for all accounts after processing invoices.

## Expected Budget Violations

Based on the invoices, here's what should trigger escalations:

| Invoice | Account | Monthly Budget | Amount | Usage | Status | Escalates? |
|---------|---------|---|--------|-------|--------|-----------|
| HC-001 | 6100 | $6,000 | $1,200 | 20% | WITHIN | No |
| HC-001 | 6300 | $150 | $1,250 | 833% | OVER | Yes* |
| HC-001 | 6200 | $200 | $300 | 150% | OVER | Yes |
| HC-001 | 6400 | $200 | $500 | 250% | OVER | Yes |
| HC-002 | 6500 | $1,000 | $5,800 | 580% | OVER | Yes |
| HC-003 | 6600 | $1,200 | $1,850 | 154% | OVER | Yes |

*Note: Account 6300 printing budget of $150/month is very tight. Any significant order exceeds it. This is intentional to test over-budget scenarios.

## Troubleshooting

### Budget not loading
- Ensure CSV/Excel has correct column headers: `account_number`, `account_name`, `annual_budget`, and month columns (`jan`, `feb`, etc.)
- Verify all account numbers exist in church's COA
- Check for encoding issues (UTF-8 recommended)

### Invoices not triggering escalation
- Verify budget was uploaded successfully: Check `/api/churches/holy_comforter/budget`
- Check `budget_warning_threshold` setting (default 0.80)
- Ensure YTD is tracking: Check `/api/churches/holy_comforter/budget/variance-report`
- Verify account numbers in invoice match budget accounts

### YTD not updating
- YTD only updates after EMIT status (not on rejection)
- Check that invoices are being approved (not rejected)
- Verify `ProcessingJob.status == EMITTED` in logs
- Check that `save_accounting_context()` is being called

## Next Steps After Testing

1. Adjust monthly budgets based on actual church spending patterns
2. Set appropriate warning thresholds for your congregation
3. Create monthly variance reports for vestry review
4. Use budget information to inform stewardship campaigns
5. Plan mid-year budget amendments if needed

