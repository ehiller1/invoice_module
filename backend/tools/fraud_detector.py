"""Fraud detection tool — evaluates fraud signals in church invoices."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal
from typing import List, Optional
import re

from ..models import ClassifiedLineItem, InvoiceDocument, AccountingContext

_PERSONAL_BENEFIT = frozenset([
    "vacation", "personal", "gift", "bonus", "award", "prize", "holiday",
    "anniversary", "birthday", "spa", "hotel stay", "resort", "cruise",
])

_INDIVIDUAL_NAME = re.compile(
    r"^(Mr\.|Mrs\.|Ms\.|Dr\.|Rev\.|Pastor\s)?\b[A-Z][a-z]+ [A-Z][a-z]+\b$"
)
_ROUND_AMT = re.compile(r"^\d+\.00$")


@dataclass
class FraudSignal:
    signal_id: str
    category: str
    description: str
    weight: float
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FraudAssessment:
    fraud_level: str
    fraud_score: float
    signals: List[FraudSignal] = field(default_factory=list)
    recommended_action: str = "APPROVE"

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _level(score: float) -> str:
    if score < 0.20:
        return "LOW"
    if score < 0.40:
        return "MEDIUM"
    if score < 0.60:
        return "HIGH"
    return "CRITICAL"


def _action(level: str) -> str:
    return {
        "LOW": "APPROVE",
        "MEDIUM": "FLAG_FOR_TREASURER",
        "HIGH": "FLAG_FOR_FINANCE_COMMITTEE",
        "CRITICAL": "ESCALATE_TO_AUDITOR",
    }.get(level, "APPROVE")


def assess_fraud(
    invoice: InvoiceDocument,
    classified: List[ClassifiedLineItem],
    ctx: AccountingContext,
    prior_invoice_numbers: Optional[List[str]] = None,
) -> FraudAssessment:
    prior = set(prior_invoice_numbers or [])
    signals: List[FraudSignal] = []
    total = 0.0
    cap = float(ctx.capitalisation_threshold_usd)

    # === A: Document Integrity ===
    inv_num = (invoice.invoice_number or "").strip()
    if not inv_num or inv_num.upper() in ("N/A", "NA", "NONE", ""):
        w = 0.25
        signals.append(FraudSignal("MISSING_INVOICE_NUMBER", "A",
            "Invoice has no invoice number", w, f"invoice_number='{inv_num}'"))
        total += w
    elif inv_num in prior:
        w = 0.40
        signals.append(FraudSignal("DUPLICATE_INVOICE_NUMBER", "A",
            f"Invoice number {inv_num} has been submitted before", w,
            f"Duplicate of prior submission: {inv_num}"))
        total += w

    days_old = (date.today() - invoice.invoice_date).days
    if days_old > 60:
        w = 0.20
        signals.append(FraudSignal("BACKDATED_INVOICE", "A",
            f"Invoice is {days_old} days old (submitted >60 days after date)", w,
            f"Invoice date: {invoice.invoice_date}; days since: {days_old}"))
        total += w

    if invoice.line_items:
        computed = sum(li.amount for li in invoice.line_items)
        diff = abs(computed + invoice.tax_amount - invoice.total_amount)
        if diff > Decimal("0.02"):
            w = 0.35
            signals.append(FraudSignal("TOTAL_MISMATCH", "A",
                "Invoice total does not equal sum of line items plus tax", w,
                f"Line sum: ${computed}; tax: ${invoice.tax_amount}; stated total: ${invoice.total_amount}; diff: ${diff:.2f}"))
            total += w

    # === B: Amount Patterns ===
    tot_f = float(invoice.total_amount)
    if cap * 0.90 <= tot_f < cap:
        pct = (cap - tot_f) / cap * 100
        w = 0.30
        signals.append(FraudSignal("AMOUNT_BELOW_THRESHOLD", "B",
            f"Total ${tot_f:.2f} is {pct:.1f}% below the ${cap:,.0f} capitalisation threshold", w,
            f"Invoice: ${tot_f:.2f}; threshold: ${cap:,.0f}"))
        total += w

    if _ROUND_AMT.match(f"{invoice.total_amount:.2f}") and tot_f >= 500 and invoice.tax_amount == Decimal("0"):
        w = 0.12
        signals.append(FraudSignal("ROUND_NUMBER_NO_TAX", "B",
            "Round-dollar invoice with no tax (common in fictitious invoice schemes)", w,
            f"Total: ${tot_f:.2f}; tax: $0.00"))
        total += w

    # === C: Vendor Anomalies ===
    vendor = invoice.vendor_name.strip()
    if _INDIVIDUAL_NAME.match(vendor):
        w = 0.18
        signals.append(FraudSignal("INDIVIDUAL_NAME_VENDOR", "C",
            "Vendor name appears to be an individual (personal payment risk)", w,
            f"Vendor: '{vendor}'"))
        total += w

    if not invoice.vendor_address or len(invoice.vendor_address.strip()) < 5:
        w = 0.12
        signals.append(FraudSignal("MISSING_VENDOR_ADDRESS", "C",
            "Vendor has no verifiable address on invoice", w,
            f"vendor_address='{invoice.vendor_address}'"))
        total += w

    # === D: Classification Red Flags ===
    for li in invoice.line_items:
        desc = li.description.lower()
        if any(kw in desc for kw in _PERSONAL_BENEFIT):
            w = 0.28
            signals.append(FraudSignal("PERSONAL_BENEFIT_KEYWORD", "D",
                "Line item contains personal benefit indicator", w,
                f"Line: '{li.description}'"))
            total = min(1.0, total + w)
            break

    for cl in classified:
        if "BENEVOLENCE" in cl.expense_category and not invoice.memo:
            w = 0.22
            signals.append(FraudSignal("BENEVOLENCE_NO_DOCUMENTATION", "D",
                "Benevolence payment with no memo/documentation", w,
                "Benevolence category detected; memo is empty"))
            total = min(1.0, total + w)
            break

    total = min(1.0, total)
    fraud_level = _level(total)
    return FraudAssessment(
        fraud_level=fraud_level,
        fraud_score=round(total, 3),
        signals=signals,
        recommended_action=_action(fraud_level),
    )
