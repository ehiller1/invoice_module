"""Payment deduplication integration — Phase 9."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from ...tools.payment_dedup_store import get_payment_dedup_store
from ..guiders.base import Decision


class PaymentDedupIntegration:
    """Integrates payment deduplication into approval workflow."""

    def __init__(self):
        self.store = get_payment_dedup_store()

    def check_for_duplicate(
        self,
        church_id: str,
        vendor: str,
        amount: Decimal,
        payment_date: datetime,
        reference_id: str,
    ) -> tuple[Optional[Decision], Optional[str]]:
        """Check if payment looks like a duplicate.

        Returns:
            (decision, reason): Decision.BLOCK if exact dup, Decision.ESCALATE if probable,
                               None if no issues found.
        """
        # Check for exact duplicate
        if self.store.is_exact_duplicate(church_id, vendor, amount, payment_date):
            return Decision.BLOCK, "Exact duplicate payment detected within 24 hours"

        # Check for probable duplicates
        probable_dups = self.store.find_probable_duplicates(
            church_id,
            vendor,
            amount,
            days_lookback=7,
        )

        if probable_dups:
            count = len(probable_dups)
            return (
                Decision.ESCALATE,
                f"Probable duplicate: {count} recent payment(s) to {vendor} for ${amount}",
            )

        return None, None

    def record_payment_approved(
        self,
        church_id: str,
        vendor: str,
        amount: Decimal,
        payment_date: datetime,
        reference_id: str,
        payment_method: str = "CHECK",
        metadata: Optional[dict] = None,
    ) -> None:
        """Record an approved payment in history."""
        self.store.record_payment(
            church_id=church_id,
            vendor=vendor,
            amount=amount,
            payment_date=payment_date,
            reference_id=reference_id,
            payment_method=payment_method,
            metadata=metadata or {"approval_status": "APPROVED"},
        )

    def get_payment_history(
        self,
        church_id: str,
        vendor: Optional[str] = None,
        amount: Optional[Decimal] = None,
        days_lookback: int = 7,
    ) -> list[dict]:
        """Get payment history for a church."""
        return self.store.get_payment_history(
            church_id,
            vendor=vendor,
            amount=amount,
            days_lookback=days_lookback,
        )


# Singleton
_dedup_integration: Optional[PaymentDedupIntegration] = None


def get_payment_dedup_integration() -> PaymentDedupIntegration:
    """Get or create singleton."""
    global _dedup_integration
    if _dedup_integration is None:
        _dedup_integration = PaymentDedupIntegration()
    return _dedup_integration
