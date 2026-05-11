"""Test data factories - replace hard-coded test data with parameterized builders.

These factories generate test objects with sensible defaults that can be easily
customized by passing keyword arguments. This replaces inline helper functions
like _je_template() and _make_je() with reusable, flexible builders.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from backend import config
from backend.models.schemas import (
    Account, AccountingContext, BudgetMonth, BudgetPlan, DenominationType,
    Fund, FundCategory, InvoiceDocument, JEStatus, JournalEntry,
    JournalEntryLine, PaymentMethod, RestrictionClass, Vendor,
)


class JournalEntryFactory:
    """Factory for generating test JournalEntry objects."""

    @staticmethod
    def build(
        entry_id: str = "JE-TEST-001",
        church_id: str = "test_church",
        fiscal_year: int = 2026,
        accounting_period: str = "2026-05",
        entry_date: Optional[date] = None,
        reference: str = "TEST-001",
        vendor_name: str = "Test Vendor",
        description: str = "Test Journal Entry",
        status: JEStatus = JEStatus.DRAFT,
        debit_amount: str = "100.00",
        debit_account: str = "7100",
        debit_account_name: str = "Rent/Mortgage",
        credit_account: str = "2010",
        credit_account_name: str = "Accounts Payable",
        fund_id: str = "GEN",
        fund_name: str = "General",
        **kwargs,
    ) -> JournalEntry:
        """Build a JournalEntry with default test values.

        Args:
            entry_id: Journal entry ID
            church_id: Church identifier
            fiscal_year: Fiscal year
            accounting_period: Period in YYYY-MM format
            entry_date: Entry date (defaults to today)
            reference: Reference number/invoice number
            vendor_name: Vendor/payee name
            description: Entry description
            status: Entry status
            debit_amount: Amount for debit line (credit will match)
            debit_account: Debit account number
            debit_account_name: Debit account name
            credit_account: Credit account number
            credit_account_name: Credit account name
            fund_id: Fund ID
            fund_name: Fund name
            **kwargs: Additional fields to override

        Returns:
            JournalEntry object
        """
        if entry_date is None:
            entry_date = date.today()

        amt = Decimal(debit_amount)

        je = JournalEntry(
            entry_id=entry_id,
            church_id=church_id,
            fiscal_year=fiscal_year,
            accounting_period=accounting_period,
            entry_date=entry_date,
            reference=reference,
            vendor_name=vendor_name,
            description=description,
            status=status,
            lines=[
                JournalEntryLine(
                    sequence=1,
                    account_number=debit_account,
                    account_name=debit_account_name,
                    fund_id=fund_id,
                    fund_name=fund_name,
                    debit=amt,
                    credit=Decimal("0"),
                    memo="",
                ),
                JournalEntryLine(
                    sequence=2,
                    account_number=credit_account,
                    account_name=credit_account_name,
                    fund_id=fund_id,
                    fund_name=fund_name,
                    debit=Decimal("0"),
                    credit=amt,
                    memo="",
                ),
            ],
            total_debits=amt,
            total_credits=amt,
            balanced=True,
        )

        # Apply any overrides from kwargs
        for key, value in kwargs.items():
            if hasattr(je, key):
                setattr(je, key, value)

        return je

    @staticmethod
    def build_recurring_template(
        church_id: str = "test_church",
        amount: str = "100.00",
        debit_account: str = "7100",
        credit_account: str = "2010",
        description: str = "Monthly rent",
        reference: str = "RECUR",
        **kwargs,
    ) -> dict:
        """Build a recurring JE template dict (for POST /api/jes/recurring).

        Returns a dict shaped for the recurring JE endpoint, not a full JournalEntry object.
        """
        amt = Decimal(amount)
        return {
            "entry_id": "TPL-001",
            "church_id": church_id,
            "fiscal_year": 2026,
            "accounting_period": "2026-05",
            "entry_date": "2026-05-06",
            "reference": reference,
            "vendor_name": "Recurring Payee",
            "description": description,
            "status": "DRAFT",
            "lines": [
                {
                    "sequence": 1,
                    "account_number": debit_account,
                    "account_name": "Expense Account",
                    "fund_id": "GEN",
                    "fund_name": "General",
                    "debit": str(amt),
                    "credit": "0",
                    "memo": "",
                },
                {
                    "sequence": 2,
                    "account_number": credit_account,
                    "account_name": "Accounts Payable",
                    "fund_id": "GEN",
                    "fund_name": "General",
                    "debit": "0",
                    "credit": str(amt),
                    "memo": "",
                },
            ],
            "total_debits": str(amt),
            "total_credits": str(amt),
            "balanced": True,
            **kwargs,
        }


class VendorFactory:
    """Factory for generating test Vendor objects."""

    @staticmethod
    def build(
        vendor_id: str = "V-001",
        church_id: str = "test_church",
        name: str = "Test Vendor",
        payment_methods: Optional[List[PaymentMethod]] = None,
        preferred_method: PaymentMethod = PaymentMethod.ACH,
        ach_routing: str = "111111111",
        ach_account_last4: str = "1234",
        check_payee_name: Optional[str] = None,
        **kwargs,
    ) -> Vendor:
        """Build a Vendor with default test values.

        Args:
            vendor_id: Vendor ID
            church_id: Church identifier
            name: Vendor name
            payment_methods: List of accepted payment methods
            preferred_method: Preferred payment method
            ach_routing: ACH routing number (test value)
            ach_account_last4: Last 4 digits of ACH account
            check_payee_name: Payee name for checks
            **kwargs: Additional fields to override

        Returns:
            Vendor object
        """
        if payment_methods is None:
            payment_methods = [PaymentMethod.ACH, PaymentMethod.CHECK]

        vendor = Vendor(
            vendor_id=vendor_id,
            church_id=church_id,
            name=name,
            payment_methods=payment_methods,
            preferred_method=preferred_method,
            ach_routing=ach_routing,
            ach_account_last4=ach_account_last4,
            check_payee_name=check_payee_name or name,
        )

        # Apply overrides
        for key, value in kwargs.items():
            if hasattr(vendor, key):
                setattr(vendor, key, value)

        return vendor


class BudgetPlanFactory:
    """Factory for generating test BudgetPlan objects."""

    @staticmethod
    def build(
        church_id: str = "test_church",
        fiscal_year: int = 2026,
        accounts: Optional[Dict[str, Dict[str, Any]]] = None,
        **kwargs,
    ) -> BudgetPlan:
        """Build a BudgetPlan with monthly buckets.

        Args:
            church_id: Church identifier
            fiscal_year: Fiscal year
            accounts: Dict of account_number -> budget data
                e.g., {"7100": {"annual_total": "50000"}}
            **kwargs: Additional fields to override

        Returns:
            BudgetPlan object
        """
        if accounts is None:
            accounts = {
                "7100": {"annual_total": "60000"},  # Rent
                "5100": {"annual_total": "120000"},  # Clergy Salary
                "7200": {"annual_total": "12000"},  # Utilities
            }

        # Build monthly buckets (equal distribution across 12 months)
        months: List[BudgetMonth] = []
        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]

        for account_num, acct_data in accounts.items():
            annual = Decimal(str(acct_data.get("annual_total", "0")))
            monthly = annual / 12 if annual else Decimal("0")

            for month_num in range(1, 13):
                months.append(
                    BudgetMonth(
                        account_number=account_num,
                        month=month_names[month_num - 1],
                        month_number=month_num,
                        annual_total=annual,
                        budgeted_amount=monthly,
                    )
                )

        plan = BudgetPlan(
            church_id=church_id,
            fiscal_year=fiscal_year,
            months=months,
        )

        # Apply overrides
        for key, value in kwargs.items():
            if hasattr(plan, key):
                setattr(plan, key, value)

        return plan


class AccountingContextFactory:
    """Factory for generating test AccountingContext objects."""

    @staticmethod
    def build(
        church_id: str = "test_church",
        church_name: str = "Test Church",
        denomination_type: DenominationType = DenominationType.OTHER,
        fiscal_year: int = 2026,
        accounts: Optional[List[Account]] = None,
        funds: Optional[List[Fund]] = None,
        **kwargs,
    ) -> AccountingContext:
        """Build a minimal AccountingContext for testing.

        Args:
            church_id: Church identifier
            church_name: Church name
            denomination_type: Denomination
            fiscal_year: Fiscal year
            accounts: Custom accounts (defaults to minimal set)
            funds: Custom funds (defaults to minimal set)
            **kwargs: Additional fields to override

        Returns:
            AccountingContext object
        """
        if accounts is None:
            accounts = [
                Account(
                    account_number="1000",
                    account_name="Cash",
                    account_type="Asset",
                    fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                ),
                Account(
                    account_number="2010",
                    account_name="Accounts Payable",
                    account_type="Liability",
                    fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                ),
                Account(
                    account_number="3000",
                    account_name="Net Assets",
                    account_type="Equity",
                    fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                ),
                Account(
                    account_number="4000",
                    account_name="Donations",
                    account_type="Revenue",
                    fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                ),
                Account(
                    account_number="7100",
                    account_name="Rent/Mortgage",
                    account_type="Expense",
                    fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                ),
                Account(
                    account_number="5100",
                    account_name="Salaries",
                    account_type="Expense",
                    fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                ),
            ]

        if funds is None:
            funds = [
                Fund(
                    fund_id="GEN",
                    fund_name="General Fund",
                    fund_category=FundCategory.GENERAL_OPERATING,
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                    current_balance=Decimal("10000"),
                ),
            ]

        ctx = AccountingContext(
            church_id=church_id,
            church_name=church_name,
            denomination_type=denomination_type,
            fiscal_year=fiscal_year,
            fiscal_year_start=date(fiscal_year, 1, 1),
            accounts=accounts,
            funds=funds,
            capitalisation_threshold_usd=Decimal("1000"),
            parsonage_allowance_current_year=Decimal("0"),
            parsonage_allowance_used_ytd=Decimal("0"),
        )

        # Apply overrides
        for key, value in kwargs.items():
            if hasattr(ctx, key):
                setattr(ctx, key, value)

        return ctx
