"""Centralized configuration management.

This module consolidates all hard-coded constants, thresholds, and defaults
that were previously scattered throughout the codebase.

All values can be overridden via environment variables.
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

# ============================================================================
# Church & Accounting Defaults
# ============================================================================

# Default church ID for operations (can be overridden by request path/header)
DEFAULT_CHURCH_ID = os.environ.get("DEFAULT_CHURCH_ID", "holy_comforter")

# Test church ID for integration tests
TEST_CHURCH_ID = os.environ.get("TEST_CHURCH_ID", "test_church")

# Current fiscal year (defaults to current calendar year)
FISCAL_YEAR = int(os.environ.get("FISCAL_YEAR", str(datetime.now().year)))

# Capitalization threshold in USD (assets >= this amount are capitalized)
CAPITALIZATION_THRESHOLD_USD = Decimal(
    os.environ.get("CAPITALIZATION_THRESHOLD_USD", "2500")
)

# ============================================================================
# Standard GL Account Numbers
# ============================================================================
# These are the "standard" account numbers used across the system.
# Note: Actual account numbers per church come from the database;
# these are fallbacks for when database is not available or for defaults.

STANDARD_ACCOUNTS = {
    # Assets
    "CASH_CHECKING": "1000",
    "BUILDING_FUND_CASH": "1020",
    "MISSIONS_CASH": "1030",
    "LAND": "1500",
    "BUILDINGS": "1510",
    "EQUIPMENT_OFFICE": "1520",
    "EQUIPMENT_HVAC": "1530",
    "VEHICLES": "1540",
    # Liabilities
    "ACCOUNTS_PAYABLE": "2010",
    "DESIGNATED_GIFTS_LIABILITY": "2020",
    "PAYROLL_LIABILITIES": "2030",
    # Equity
    "NET_ASSETS_NO_RESTRICTION": "3100",
    "NET_ASSETS_PURPOSE_RESTRICTED": "3200",
    "NET_ASSETS_ENDOWMENT": "3300",
    # Revenue
    "TITHES_AND_OFFERINGS": "4100",
    "DESIGNATED_GIFTS_BUILDING": "4200",
    "DESIGNATED_GIFTS_MISSIONS": "4210",
    "DESIGNATED_GIFTS_YOUTH": "4220",
    # Personnel (Expense)
    "CLERGY_SALARY": "5100",
    "CLERGY_HOUSING_ALLOWANCE": "5101",
    "CLERGY_PARSONAGE_UTILITIES": "5102",
    "SECA_REIMBURSEMENT": "5110",
    "LAY_STAFF_WAGES": "5200",
    "EMPLOYEE_BENEFITS_HEALTH": "5300",
    "EMPLOYEE_BENEFITS_RETIREMENT": "5310",
    # Ministry Programs (Expense)
    "WORSHIP_MUSIC": "6100",
    "WORSHIP_ALTAR_COMMUNION": "6110",
    "CHILDRENS_MINISTRY": "6200",
    "YOUTH_MINISTRY_GENERAL": "6300",
    "YOUTH_MINISTRY_RESTRICTED": "6310",
    "ADULT_EDUCATION": "6400",
    "MISSIONS_LOCAL": "6500",
    "MISSIONS_PASS_THROUGH": "6600",
    "PASTORAL_CARE": "6700",
    "BENEVOLENCE_DISBURSEMENTS": "6900",
    # Facility & Operations (Expense)
    "MORTGAGE_RENT": "7100",
    "UTILITIES_ELECTRIC": "7200",
    "UTILITIES_GAS": "7210",
    "UTILITIES_WATER_SEWER": "7220",
    "UTILITIES_INTERNET_PHONE": "7230",
    "MAINTENANCE_REPAIRS": "7300",
    "JANITORIAL_SERVICES": "7310",
    "LAWN_AND_GROUNDS": "7320",
    "INSURANCE_PROPERTY_LIABILITY": "7400",
    "TECHNOLOGY_SOFTWARE_SUBSCRIPTIONS": "7500",
    # Administration (Expense)
    "OFFICE_SUPPLIES": "8100",
    "LEGAL_AUDIT": "8200",
    "APPORTIONMENT_CONFERENCE": "8300",
    "APPORTIONMENT_DISTRICT": "8310",
    "STEWARDSHIP_FUNDRAISING": "8400",
    # Capital (Expense/Asset)
    "DEPRECIATION_EXPENSE": "9100",
    "CAPITAL_EXPENDITURES_BUILDING": "9200",
    "CAPITAL_EXPENDITURES_EQUIPMENT": "9210",
    "LOAN_PRINCIPAL": "9300",
}

# For backward compatibility - short name mappings
AP_ACCOUNT = STANDARD_ACCOUNTS["ACCOUNTS_PAYABLE"]
CASH_ACCOUNT = STANDARD_ACCOUNTS["CASH_CHECKING"]
CLERGY_SALARY_ACCOUNT = STANDARD_ACCOUNTS["CLERGY_SALARY"]

# ============================================================================
# Financial Thresholds & Percentages
# ============================================================================

# Default apportionment percentages by denomination
APPORTIONMENT_PERCENTAGES = {
    "UMC": {
        "CONFERENCE": Decimal("12.0"),
        "DISTRICT": Decimal("3.0"),
    },
    "EPISCOPAL": {
        "DIOCESAN": Decimal("12.5"),
    },
}

# Clergy allowance defaults by denomination (in USD)
CLERGY_ALLOWANCE_DEFAULTS = {
    "UMC": Decimal("36000"),
    "EPISCOPAL": Decimal("42000"),
}

# CPF (Church Pension Fund) assessment rate for Episcopal churches
CPF_ASSESSMENT_RATE = Decimal("18.0")

# ============================================================================
# Fund Categories & Restrictions
# ============================================================================

# Standard fund IDs used across churches
STANDARD_FUNDS = {
    "GEN": "General Operating Fund",
    "BLDG": "Building Fund",
    "MISS": "Missions Fund",
    "YOUTH": "Youth Ministry Fund",
    "ENDOW": "Endowment Fund",
    "BENEV": "Benevolence Fund",
}

# ============================================================================
# Feature Flags
# ============================================================================

# Enable various phases of functionality
PHASE_FLAGS = {
    "PHASE_5": os.environ.get("EMBARK_MEMBRANE_PHASE_5", "1") == "1",
    "PHASE_6": os.environ.get("EMBARK_MEMBRANE_PHASE_6", "1") == "1",
    "PHASE_7": os.environ.get("EMBARK_MEMBRANE_PHASE_7", "1") == "1",
    "PHASE_8": os.environ.get("EMBARK_MEMBRANE_PHASE_8", "1") == "1",
}

# ============================================================================
# Transport Backend
# ============================================================================

TRANSPORT_BACKEND = os.environ.get("TRANSPORT_BACKEND", "local")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PLATFORM_MESH_URL = os.environ.get("PLATFORM_MESH_URL", "")

# ============================================================================
# Test Configuration
# ============================================================================

# Standard test data values (used by test factories)
TEST_VENDOR_ROUTING = "111111111"
TEST_VENDOR_ACH_ACCOUNT = "1234567890"
TEST_JOURNAL_ENTRY_AMOUNT = Decimal("100.00")
TEST_JOURNAL_ENTRY_DEBIT_ACCOUNT = STANDARD_ACCOUNTS["MORTGAGE_RENT"]
TEST_JOURNAL_ENTRY_CREDIT_ACCOUNT = STANDARD_ACCOUNTS["ACCOUNTS_PAYABLE"]
