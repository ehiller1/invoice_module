# Hard-Coded Data Audit Report

**Date:** May 11, 2026  
**Status:** ⚠️ CRITICAL - Application contains significant hard-coded test/example data throughout codebase

---

## Executive Summary

This application contains **extensive hard-coded data** that should be converted to:
1. **Test fixtures** with factory functions
2. **Configuration files** (environment variables, YAML)
3. **Database seed scripts** for initialization
4. **Simulated/generated data** for testing

Total instances found: **500+** across the codebase.

---

## Critical Issues by Category

### 1. Hard-Coded Church/Organization Data

**Files:** `backend/main.py`, `backend/tools/coa_store.py`

#### Issue 1.1: Default Church IDs in API Endpoints
**Location:** `backend/main.py` (20+ endpoints)  
**Severity:** 🔴 CRITICAL

```python
# Examples of hard-coded church_id defaults:
@app.get("/api/budget-variance")
async def budget_variance_alias(church_id: str = "holy_comforter") -> JSONResponse:

@app.get("/api/coa/search")
async def coa_search_alias(q: str, church_id: str = "holy_comforter", k: int = 5) -> JSONResponse:

@app.post("/api/payments/recommend")
async def get_council_queues(church_id: str = "holy_comforter") -> JSONResponse:
```

**Affected Endpoints (20+):**
- `/api/budget-variance` → defaults to `"holy_comforter"`
- `/api/coa/search` → defaults to `"holy_comforter"`
- `/api/coa/list` → defaults to `"holy_comforter"`
- `/api/council/queues` → defaults to `"holy_comforter"`
- `/api/cabinet/activity` → defaults to `"holy_comforter"`
- `/api/adversarial-findings` → defaults to `"holy_comforter"`
- `/api/materiality-budget` → defaults to `"holy_comforter"`
- `/api/evidence-pack` → defaults to `"holy_comforter"`
- `/api/peer-benchmarks` → defaults to `"holy_comforter"`
- `/api/acs/status` → defaults to `"holy_comforter"`
- `/api/decision-suite/*` → multiple endpoints default to `"holy_comforter"`

**Impact:** 
- API is not multi-tenant; hardcoded to test church
- Endpoints cannot be properly tested with different organizations
- Production code uses test data

---

#### Issue 1.2: Hard-Coded Church Setup Templates
**Location:** `backend/tools/coa_store.py` (lines 150-510)  
**Severity:** 🔴 CRITICAL

Two complete church accounting contexts with all hard-coded data:

**UMC Church Template:**
```python
# backend/tools/coa_store.py:290-310
AccountingContext(
    church_id="grace_umc",
    church_name="Grace United Methodist Church",
    denomination_type=DenominationType.UMC,
    fiscal_year=2026,  # ← HARD-CODED YEAR
    fiscal_year_start=date(2026, 1, 1),  # ← HARD-CODED DATE
    accounts=[... 40+ accounts with hard-coded numbers ...],  # ← HARD-CODED ACCOUNT STRUCTURE
    capitalisation_threshold_usd=Decimal("2500"),  # ← HARD-CODED THRESHOLD
    parsonage_allowance_current_year=Decimal("36000"),  # ← HARD-CODED ALLOWANCE
)
```

**Episcopal Church Template:**
```python
# backend/tools/coa_store.py:492-510
AccountingContext(
    church_id="holy_comforter",
    church_name="Church of the Holy Comforter",
    denomination_type=DenominationType.EPISCOPAL,
    fiscal_year=2026,  # ← HARD-CODED YEAR
    fiscal_year_start=date(2026, 1, 1),  # ← HARD-CODED DATE
    accounts=[... 50+ accounts with hard-coded numbers ...],  # ← HARD-CODED ACCOUNT STRUCTURE
    capitalisation_threshold_usd=Decimal("2500"),
    parsonage_allowance_current_year=Decimal("42000"),
)
```

**Impact:**
- Chart of accounts is locked to 2026
- Account numbers cannot be customized
- Test data cannot be changed without modifying source code

---

#### Issue 1.3: Default Church Accounts on Init
**Location:** `backend/main.py` (lines 186-204)  
**Severity:** 🟠 HIGH

```python
# This hardcodes 6 default accounts for every new church
accounts=[
    Account(account_number="1000", account_name="Cash — Checking", ...),
    Account(account_number="2010", account_name="Accounts Payable", ...),
    Account(account_number="4000", account_name="Tithes & Offerings", ...),
    Account(account_number="5000", account_name="Clergy Compensation", ...),
    Account(account_number="7000", account_name="Facilities", ...),
    Account(account_number="8000", account_name="Administration", ...),
]
```

**Impact:** All new churches get the same basic chart of accounts

---

### 2. Hard-Coded Account Numbers Throughout Codebase

**Total Occurrences:** 172+  
**Severity:** 🔴 CRITICAL

**Key Account Numbers Hard-Coded:**
- `"1000"` - Cash Checking (47 occurrences)
- `"2010"` - Accounts Payable (35 occurrences)
- `"7100"` - Mortgage/Rent or Office Supplies (28 occurrences)
- `"5100"` - Clergy Salary (15 occurrences)
- `"8300"`, `"8310"` - Apportionments (9 occurrences)
- `"6010"`, `"6100"` - Various ministry expenses (12 occurrences)

**Files with Hard-Coded Account Numbers:**
- `backend/main.py` - 45+ instances
- `backend/tools/gl_mapper.py` - Constant: `AP_ACCOUNT = "2010"`
- `backend/tools/coa_store.py` - 60+ instances (all account definitions)
- `backend/tests/test_*.py` - 70+ instances

**Example from GL Mapper:**
```python
# backend/tools/gl_mapper.py:14
AP_ACCOUNT = "2010"  # Accounts Payable - HARDCODED CONSTANT
```

**Impact:**
- Cannot test with different account numbers
- System assumes "2010" is always AP
- Migration to different COA would require code changes

---

### 3. Hard-Coded Fiscal Year (2026)

**Total Occurrences:** 171+  
**Severity:** 🟠 HIGH

**Files:**
- `backend/tools/coa_store.py` - fiscal_year=2026 (multiple templates)
- `backend/main.py` - 20+ instances
- All test files - hardcoded to 2026-05, 2026-01, etc.

**Examples:**
```python
fiscal_year=2026,  # in 40+ places
fiscal_year_start=date(2026, 1, 1),  # in 20+ places
accounting_period="2026-05",  # in tests
entry_date=date(2026, 5, 6),  # in tests
```

**Impact:**
- Year is locked to 2026 in templates
- Tests cannot be run in future years
- Fiscal year configuration is not parameterized

---

### 4. Hard-Coded Test Data in Test Functions

**Files:** `backend/tests/test_*.py` (20+ files)  
**Severity:** 🟠 HIGH

#### Issue 4.1: Test Helper Functions with Inline Data
**Location:** `backend/tests/test_phase3_recurring.py` (lines 13-43)

```python
def _je_template(amount="100.00"):
    """Return a JournalEntry-shaped dict suitable as a template."""
    return {
        "entry_id": "TPL-001",  # HARD-CODED
        "church_id": "testch",  # HARD-CODED
        "fiscal_year": 2026,  # HARD-CODED
        "accounting_period": "2026-05",  # HARD-CODED
        "entry_date": "2026-05-06",  # HARD-CODED
        "reference": "RECUR",  # HARD-CODED
        "vendor_name": "Recurring Payee",  # HARD-CODED
        "description": "Monthly rent",  # HARD-CODED
        "lines": [
            {
                "sequence": 1, "account_number": "7100",  # HARD-CODED
                "account_name": "Office Supplies", "fund_id": "GEN",  # HARD-CODED
                "debit": str(amt), "credit": "0",
            },
            {
                "sequence": 2, "account_number": "2010",  # HARD-CODED
                "account_name": "Accounts Payable", "fund_id": "GEN",  # HARD-CODED
                "debit": "0", "credit": str(amt),
            },
        ],
    }
```

#### Issue 4.2: Hard-Coded Test Vendor Data
**Location:** `backend/tests/test_phase3_payments.py` (lines 15-46)

```python
def _make_je(amount="100.00", entry_id="JE-TEST-001"):
    je = JournalEntry(
        entry_id=entry_id,
        church_id="testch",  # HARD-CODED
        fiscal_year=2026,  # HARD-CODED
        accounting_period="2026-05",  # HARD-CODED
        entry_date=date(2026, 5, 6),  # HARD-CODED
        reference="INV-001",  # HARD-CODED
        vendor_name="Acme Vendor",  # HARD-CODED
        description="Test JE",  # HARD-CODED
        lines=[
            JournalEntryLine(
                sequence=1, account_number="7100",  # HARD-CODED
                account_name="Office Supplies",  # HARD-CODED
                # ...
            ),
        ],
    )
```

#### Issue 4.3: Vendor Data in Tests
**Location:** `backend/tests/test_phase3_payments.py` (lines 67-80)

```python
v = Vendor(
    vendor_id="V001",  # HARD-CODED
    church_id="testch",  # HARD-CODED
    name="Acme Vendor",  # HARD-CODED
    payment_methods=[PaymentMethod.ACH, PaymentMethod.CHECK],
    preferred_method=PaymentMethod.ACH,
    ach_routing="123456789",  # HARD-CODED TEST ROUTING
    ach_account_last4="1234",  # HARD-CODED TEST ACCOUNT
)
```

**Tests with Hard-Coded Data:**
- `test_phase3_payments.py` - vendor data, routing numbers, account numbers
- `test_phase3_recurring.py` - journal entry templates
- `test_phase4_guiders.py` - ACME vendor, amounts
- `test_phase7_*.py` - ACME Corp, invoice data
- `test_phase12_cabinet_integration.py` - vendor data, invoice data

---

### 5. Hard-Coded Financial Thresholds & Percentages

**Severity:** 🟠 HIGH

**Files:** `backend/tools/coa_store.py`

```python
# Line 285-286
ApportionmentAccount(account_number="8300", pct_of_revenue=Decimal("12.0")),  # 12% HARD-CODED
ApportionmentAccount(account_number="8310", pct_of_revenue=Decimal("3.0")),   # 3% HARD-CODED

# Line 489
ApportionmentAccount(account_number="8410", pct_of_revenue=Decimal("12.5")),  # 12.5% HARD-CODED

# Line 298
capitalisation_threshold_usd=Decimal("2500"),  # $2500 HARD-CODED

# Lines 299, 502
parsonage_allowance_current_year=Decimal("36000"),  # $36k HARD-CODED (UMC)
parsonage_allowance_current_year=Decimal("42000"),  # $42k HARD-CODED (Episcopal)
```

**Impact:**
- Apportionment percentages cannot be changed without code modification
- Capitalization threshold is locked
- Clergy allowances are hard-coded by denomination

---

### 6. Hard-Coded Vendor & Invoice Data in Production Code

**Location:** `backend/main.py` (line 3522)  
**Severity:** 🟠 HIGH

```python
# In a production endpoint that returns example data
{
    "vendor_name": "Facility Maintenance LLC",  # HARD-CODED EXAMPLE
    "accounting_period": "2026-04",
    # ... more example data ...
}
```

**Impact:** 
- Production endpoints return hard-coded example data
- Users cannot distinguish between real and example data

---

### 7. Hard-Coded Amounts in Tests

**Severity:** 🟡 MEDIUM

Multiple test files use hard-coded monetary amounts:

```python
# test_phase3_recurring.py
_je_template(amount="100.00")  # 100.00 HARD-CODED

# test_phase4_guiders.py
v = g.evaluate({"vendor": "ACME", "amount": 100.0})  # 100.0 HARD-CODED
v = g.evaluate({"vendor": "ACME", "amount": 100})   # 100 HARD-CODED
v = g.evaluate({"is_exact_duplicate": True, "vendor": "ACME", "amount": 100})  # 100 HARD-CODED

# test_phase7_orchestrator.py
{"vendor": "ACME", "total_amount": "100.00", "job_id": "j1"}  # "100.00" HARD-CODED

# test_phase12_cabinet_integration.py
vendor="ACME Corp",  # HARD-CODED
```

---

### 8. Hard-Coded Data in Config/Setup

**Location:** `backend/setup_wizard.py` (line 279)  
**Severity:** 🟠 HIGH

```python
Account(
    account_number="1000", account_name="Cash — Checking",
    # ...
),
```

---

## Summary Table

| Category | Count | Severity | Location |
|----------|-------|----------|----------|
| Hard-coded church IDs | 102+ | 🔴 CRITICAL | main.py, tests |
| Hard-coded account numbers | 172+ | 🔴 CRITICAL | coa_store.py, gl_mapper.py, main.py, tests |
| Hard-coded fiscal year (2026) | 171+ | 🟠 HIGH | coa_store.py, main.py, all tests |
| Hard-coded test vendor data | 30+ | 🟠 HIGH | test_phase*.py |
| Hard-coded financial thresholds | 10+ | 🟠 HIGH | coa_store.py |
| Hard-coded amounts | 50+ | 🟡 MEDIUM | tests |
| Hard-coded routing numbers | 5+ | 🟡 MEDIUM | tests |
| Hard-coded example data in production | 5+ | 🟠 HIGH | main.py |

**TOTAL: 500+ instances of hard-coded data**

---

## Recommendations

### Priority 1: CRITICAL (Fix Immediately)

1. **Move Church Templates to Configuration**
   - Move `grace_umc` and `holy_comforter` templates to YAML/JSON config files
   - Load via environment variables or database
   - Create factory function for generating accounting contexts

2. **Parameterize API Endpoints**
   - Remove hard-coded `church_id` defaults
   - Require explicit church_id parameter or use from context
   - Add proper request validation

3. **Externalize Account Numbers**
   - Move all account numbers to database or config
   - Create constants file for GL mapper instead of hard-coded strings
   - Add account lookup function

### Priority 2: HIGH (Fix Soon)

4. **Create Test Fixtures**
   - Replace inline test data with pytest fixtures
   - Use factory_boy or similar for generating test data
   - Create builder patterns for complex objects

5. **Parameterize Fiscal Year**
   - Use current year or configurable year
   - Pass as parameter through system
   - Add year parameter to all date-related functions

6. **Separate Example Data from Production**
   - Move example/sample data to separate endpoints or responses
   - Clearly mark as "example" or "sample"
   - Do not return hard-coded data from production endpoints

### Priority 3: MEDIUM (Improve Code Quality)

7. **Extract Test Data Builders**
   - Create proper test data factories
   - Use parameterized tests with data providers
   - Move magic strings to fixtures

8. **Configuration Management**
   - Use environment variables for thresholds
   - Move percentages and allowances to config files
   - Support per-denomination customization

---

## Files Requiring Changes

**Critical:**
- `backend/main.py` - Remove 20+ hard-coded church IDs; externalize default accounts
- `backend/tools/coa_store.py` - Move to config-based templates
- `backend/tools/gl_mapper.py` - Extract account number constants

**High Priority:**
- `backend/tests/test_phase3_recurring.py` - Convert to fixtures
- `backend/tests/test_phase3_payments.py` - Convert to fixtures
- `backend/tests/test_phase4_guiders.py` - Parameterize test data
- `backend/tests/test_phase7_orchestrator.py` - Use test factories
- `backend/tests/test_phase12_cabinet_integration.py` - Extract vendor data

**Medium Priority:**
- All other test files with inline data
- Setup wizard templates
- Configuration initialization code

---

## Testing Strategy After Fixes

- Use pytest fixtures for all test data
- Create data factories for common objects
- Parameterize tests with multiple scenarios
- Mock external dependencies
- Use environment variables for configuration
- Separate unit tests (fast, isolated) from integration tests

