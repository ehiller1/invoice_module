"""FR-08: Recommend a payment method for a JE based on vendor + amount."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any

from backend.models.schemas import JournalEntry, Vendor, PaymentMethod


def recommend_payment_method(
    je: JournalEntry, vendor: Optional[Vendor]
) -> Dict[str, Any]:
    """Recommend a payment method.

    Priority:
      1. Vendor's preferred_method (if it's also in their available methods).
      2. ACH if vendor is enrolled.
      3. Amount-based heuristic: very large amounts (> $5000) prefer ACH/wire
         over check.
      4. Fallback: CHECK.

    Returns: {recommended: str, options: [str], rationale: str}
    """
    # Compute total amount from debits (defensive)
    total = Decimal("0")
    for line in je.lines:
        d = getattr(line, "debit", None)
        if d is None:
            d = getattr(line, "debit_amount", Decimal("0"))
        try:
            total += Decimal(str(d))
        except Exception:
            pass

    # 1. Vendor preferred + available
    if (
        vendor
        and vendor.preferred_method
        and vendor.preferred_method in (vendor.payment_methods or [])
    ):
        return {
            "recommended": vendor.preferred_method.value,
            "options": [m.value for m in vendor.payment_methods],
            "rationale": f"{vendor.name} prefers {vendor.preferred_method.value}",
        }

    # 2. Vendor enrolled in ACH
    if vendor and PaymentMethod.ACH in (vendor.payment_methods or []):
        return {
            "recommended": "ACH",
            "options": [m.value for m in vendor.payment_methods],
            "rationale": "ACH is preferred for vendors enrolled in direct deposit",
        }

    # 3. Large amount heuristic
    if total > Decimal("5000"):
        opts = (
            [m.value for m in vendor.payment_methods]
            if vendor and vendor.payment_methods
            else ["ACH", "WIRE", "CHECK"]
        )
        return {
            "recommended": "ACH",
            "options": opts,
            "rationale": (
                f"Amount ${total} exceeds $5000 threshold; prefer ACH or wire over check"
            ),
        }

    # 4. Fallback
    opts = (
        [m.value for m in vendor.payment_methods]
        if vendor and vendor.payment_methods
        else ["CHECK", "ACH", "CREDIT_CARD"]
    )
    return {
        "recommended": "CHECK",
        "options": opts,
        "rationale": "Default to check; vendor not in ACH; user can override",
    }
