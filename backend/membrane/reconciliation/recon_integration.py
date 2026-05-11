"""Reconciliation exception integration — Phase 9."""

from typing import Any, Dict, Optional

from ...tools.recon_exception_store import get_recon_exception_store
from ..guiders.base import Decision


class ReconciliationIntegration:
    """Integrates reconciliation exception handling into workflow."""

    def __init__(self):
        self.store = get_recon_exception_store()

    def record_unmatched_transaction(
        self,
        church_id: str,
        txn_id: str,
        amount: str,
        description: str,
        exception_type: str = "BANK_ONLY",
        days_unmatched: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record an unmatched bank or ACS transaction.

        Args:
            exception_type: "BANK_ONLY" (in bank but not ACS),
                          "ACS_ONLY" (in ACS but not bank),
                          "AMOUNT_MISMATCH" (matched but amount differs)
        Returns:
            exception_id
        """
        return self.store.record_exception(
            church_id=church_id,
            exception_type=exception_type,
            txn_id=txn_id,
            amount=amount,
            description=description,
            days_unmatched=days_unmatched,
            metadata=metadata,
        )

    def check_reconciliation_status(
        self,
        church_id: str,
    ) -> tuple[Optional[Decision], Optional[str]]:
        """Check reconciliation status and decide verdict.

        Returns:
            (decision, reason): Decision.ESCALATE if unresolved exceptions exist,
                               None if reconciliation is clean.
        """
        exceptions = self.store.get_unresolved_exceptions(church_id)

        if not exceptions:
            return None, None

        # Escalate if there are unresolved exceptions
        summary = self.store.get_exception_summary(church_id)
        unresolved = summary.get("unresolved_count", 0)
        oldest_days = summary.get("oldest_unresolved_days", 0)

        reason = f"Unresolved reconciliation exceptions: {unresolved} items, oldest {oldest_days} days"

        return Decision.ESCALATE, reason

    def get_exceptions(
        self,
        church_id: str,
        resolved: Optional[bool] = None,
    ) -> list[Dict[str, Any]]:
        """Get reconciliation exceptions."""
        return self.store.get_exceptions(church_id, resolved=resolved)

    def get_unresolved_exceptions(self, church_id: str) -> list[Dict[str, Any]]:
        """Get unresolved exceptions."""
        return self.store.get_unresolved_exceptions(church_id)

    def resolve_exception(
        self,
        church_id: str,
        exception_id: str,
        resolution_notes: str,
    ) -> bool:
        """Mark exception as resolved."""
        return self.store.resolve_exception(
            church_id,
            exception_id,
            resolution_notes,
        )

    def get_exception_summary(self, church_id: str) -> Dict[str, Any]:
        """Get summary of exceptions."""
        return self.store.get_exception_summary(church_id)


# Singleton
_recon_integration: Optional[ReconciliationIntegration] = None


def get_reconciliation_integration() -> ReconciliationIntegration:
    """Get or create singleton."""
    global _recon_integration
    if _recon_integration is None:
        _recon_integration = ReconciliationIntegration()
    return _recon_integration
