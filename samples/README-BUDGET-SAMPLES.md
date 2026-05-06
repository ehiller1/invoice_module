# Budget Testing Samples for EIME

This directory contains sample files for testing the new budget feature in EIME.

## Files Included

### 1. Budget Spreadsheet
**`holy-comforter-budget-2024.csv`**

A complete annual budget for Holy Comforter Episcopal Church (fiscal year 2024).

**How to use:**
- Upload via the Budget Management page (`/budget.html`)
- Or test via API: `POST /api/churches/holy_comforter/budget/import-spreadsheet`

**Format:**
- CSV file with headers: Account Number, Account Name, Annual Budget, Jan, Feb, ..., Dec
- 50 accounts covering typical Episcopal church operations
- Monthly allocations (equal monthly distribution for most accounts)
- All accounts from Holy Comforter's COA

**Key accounts for testing:**
- Account 6500 (Maintenance): $1,000/month — Tests over-budget scenarios
- Account 6600 (Utilities): $1,200/month — Tests warning scenarios  
- Account 6300 (Printing): $150/month — Very tight budget for testing overages
- Account 6100 (Vestments): $500/month — Normal spending
- Account 4100 (Pledges): $180,000 total — Revenue account

**To convert to Excel:**
1. Open the CSV in Excel/LibreOffice
2. Verify data looks correct
3. Save as `.xlsx` format
4. The system will accept both CSV and Excel

### 2. Sample Invoices
Three JSON files representing different budget scenarios:

#### `sample-invoice-HC-001.json` — Normal Operations
- **Total:** $3,250
- **Accounts:** Altar vestments, hymnals, office supplies, flowers
- **Expected result:** WITHIN_BUDGET for all accounts
- **YTD impact:** Modest consumption across 4 accounts

#### `sample-invoice-HC-002.json` — Over-Budget Maintenance
- **Total:** $5,800  
- **Accounts:** All to account 6500 (Maintenance)
- **Expected result:** OVER_BUDGET (account 6500 is $1,000/month, invoice is $5,800)
- **YTD impact:** 580% of monthly maintenance budget
- **Testing focus:** Triggers HITL escalation, requires approval with attestation

#### `sample-invoice-HC-003.json` — Utility Bill
- **Total:** $1,850
- **Accounts:** All to account 6600 (Utilities)  
- **Expected result:** OVER_BUDGET or WARNING (account 6600 is $1,200/month, invoice is $1,850)
- **YTD impact:** 154% of monthly utility budget
- **Testing focus:** Borderline case testing threshold logic

**How to use:**
- **Option 1 (Recommended for now):** Use the JSON directly with test harness
- **Option 2 (Future):** Convert to PDF and upload like real invoices
  - Use any PDF generator with these line items
  - Save as PDF with filename matching invoice ID

### 3. Testing Guide
**`BUDGET-TESTING-GUIDE.md`**

Complete guide covering:
- Budget file structure and contents
- Invoice details and expected outcomes
- 7 comprehensive test scenarios
- API testing examples
- Expected budget violations
- Troubleshooting guide

## Quick Start

### Step 1: Upload Budget
```bash
# Via API
curl -X POST http://localhost:8000/api/churches/holy_comforter/budget/import-spreadsheet \
  -H "Content-Type: multipart/form-data" \
  -F "file=@holy-comforter-budget-2024.csv"
```

### Step 2: Verify Budget Loaded
```bash
curl http://localhost:8000/api/churches/holy_comforter/budget
```

### Step 3: Process Sample Invoices
Test the workflow with each invoice:

1. **HC-001 (Normal)** → Should process without escalation
2. **HC-002 (Over-budget)** → Should trigger HITL for approval
3. **HC-003 (Utility)** → Should trigger HITL if over threshold

### Step 4: Check Variance Report
```bash
curl http://localhost:8000/api/churches/holy_comforter/budget/variance-report
```

## Key Testing Points

✓ **Budget upload and parsing**
- CSV detection and column mapping
- Account validation (all accounts must exist in COA)
- Decimal precision (budget amounts)
- Monthly distributions

✓ **Budget comparison**
- WITHIN_BUDGET status (≤80% of monthly)
- WARNING status (80-100% of monthly)
- OVER_BUDGET status (>100% of monthly)
- Configurable thresholds

✓ **HITL integration**
- Budget violations in escalation_items
- Reason strings in line reasons
- Budget attestation checkbox
- Approval prevents transaction rejection

✓ **YTD tracking**
- YTD updates on EMIT
- YTD not updated on REJECT
- Correct account mapping
- Decimal precision

✓ **Dashboard integration**
- Budget consumption progress bar
- At-risk accounts counter
- Over-budget accounts counter
- Variance report access

## Data Characteristics

### Budget Totals
- **Annual budget:** $412,200
- **Monthly average:** $34,350
- **Largest account:** 4100 (Pledges) $180,000 revenue
- **Typical expense:** 6600 (Utilities) $14,400

### Realistic Patterns
- Clergy compensation (salary + benefits): 37% of budget
- Diocesan assessment: 5% of budget
- Building operation (utilities + maintenance): 20% of budget
- Ministry & outreach: 5% of budget
- Administration: 10% of budget

### Edge Cases in Budget
- Account 6300 (Printing) has very low budget ($150/month) — easy to exceed
- Account 6500 (Maintenance) has moderate budget ($1,000/month) — can be exceeded with single repair
- Revenue accounts (4100, 4200, etc.) have budgets but are not enforced the same way
- Zero-budget accounts (like 1000 Cash) are skipped in comparison

## Integration with Holy Comforter Profile

These samples work with the Holy Comforter Episcopal Church profile created in the previous build:

- **Church ID:** `holy_comforter`
- **Denomination:** EPISCOPAL
- **Fiscal Year:** 2024
- **COA Accounts:** 73 accounts (all referenced in budget)
- **Funds:** 6 funds (GEN, OUTREACH, MEMORIAL, RECTOR_DISC, ENDOW_PRIN, ENDOW_INC)

Budget can be uploaded to the same church and will integrate seamlessly.

## Next Steps for Full Testing

1. **Real PDF invoices:**
   - Scan sample invoice documents to PDF
   - Or use invoice template to create realistic PDFs
   - Upload through normal PDF invoice workflow

2. **Multi-month testing:**
   - Create additional invoices for Feb, Mar, etc.
   - Track YTD across multiple months
   - Test budget amendments mid-year

3. **Performance testing:**
   - Large budget files (500+ accounts)
   - Many invoices in sequence
   - Concurrent budget updates

4. **Audit trail testing:**
   - Track budget changes
   - Verify attestation recorded
   - Export variance reports for vestry

## Questions?

Refer to:
- `BUDGET-TESTING-GUIDE.md` — Detailed test scenarios
- `/thoughts/shared/plans/PLAN-budget-feature.md` — Implementation details
- `/thoughts/shared/handoffs/build-budget-feature/` — Architecture and research

