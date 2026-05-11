"""Phase 10.6: Guider Learning from Decision Ledger.

Guiders read recent Decision Ledger entries to learn confidence scores
from historical verdicts. This enables guiders to improve over time.
"""

from datetime import datetime, timedelta
from typing import Any
from backend.cards.ledger import get_decision_ledger


class GuiderFeedbackStore:
    """Helper for guiders to learn from Decision Ledger history."""

    def __init__(self, church_id: str):
        self.church_id = church_id
        self.ledger = get_decision_ledger(church_id)

    def get_recent_decisions_by_category(
        self, category: str, lookback_days: int = 7
    ) -> list[dict]:
        """Get recent decisions by category (for guider learning).

        Args:
            category: RECOGNIZE, CODE, ROUTE, APPROVE, OVERRIDE, DISAVOW
            lookback_days: How far back to look

        Returns:
            List of recent decision ledger entries
        """
        period_start = datetime.utcnow() - timedelta(days=lookback_days)
        return self.ledger.find_by_category(
            category=category,
            period_start=period_start,
        )

    def compute_confidence_score(
        self, category: str, lookback_days: int = 7
    ) -> float:
        """Compute confidence score based on historical approval rate.

        Args:
            category: RECOGNIZE, CODE, ROUTE, APPROVE, OVERRIDE, DISAVOW
            lookback_days: Historical window

        Returns:
            Confidence (0.0-1.0) based on approval/total ratio
        """
        decisions = self.get_recent_decisions_by_category(category, lookback_days)
        if not decisions:
            return 0.5  # Default confidence

        approved_count = sum(
            1 for d in decisions if d.get("outcome") == "accepted"
        )
        total_count = len(decisions)

        if total_count == 0:
            return 0.5

        return min(1.0, approved_count / total_count)

    def get_guider_context(
        self, category: str, lookback_days: int = 7
    ) -> dict[str, Any]:
        """Get contextual info for a guider making a decision.

        Args:
            category: Decision category
            lookback_days: Historical window

        Returns:
            Dict with recent decisions, confidence score, override count
        """
        decisions = self.get_recent_decisions_by_category(category, lookback_days)
        overrides = [
            d for d in decisions if d.get("category") == "OVERRIDE"
        ]
        approvals = [
            d for d in decisions if d.get("outcome") == "accepted"
        ]

        confidence = self.compute_confidence_score(category, lookback_days)

        return {
            "category": category,
            "recent_decisions": decisions,
            "total_decisions": len(decisions),
            "approvals": len(approvals),
            "overrides": len(overrides),
            "confidence_score": confidence,
            "lookback_days": lookback_days,
        }

    def find_similar_decisions(
        self,
        category: str,
        criteria: dict[str, Any],
        lookback_days: int = 30,
    ) -> list[dict]:
        """Find similar past decisions for reference.

        Args:
            category: Decision category
            criteria: Dict of attributes to match (e.g., {"account": "10000"})
            lookback_days: Historical window

        Returns:
            List of similar past decisions
        """
        decisions = self.get_recent_decisions_by_category(category, lookback_days)
        similar = []

        for decision in decisions:
            metadata = decision.get("metadata", {})
            if isinstance(metadata, dict):
                # Check if metadata matches criteria
                matches = all(
                    metadata.get(k) == v for k, v in criteria.items()
                )
                if matches:
                    similar.append(decision)

        return similar

    def get_override_patterns(self, lookback_days: int = 30) -> dict[str, Any]:
        """Analyze override patterns (for audit/improvement).

        Args:
            lookback_days: Historical window

        Returns:
            Dict with override statistics
        """
        period_start = datetime.utcnow() - timedelta(days=lookback_days)
        all_entries = self.ledger.all_entries()

        # Note: DecisionCategory.OVERRIDE has value "override" (lowercase)
        overrides = [
            e
            for e in all_entries
            if e.get("category") == "override"
            and datetime.fromisoformat(e.get("timestamp", "")) >= period_start
        ]

        # Group by category
        by_category = {}
        for override in overrides:
            original_category = override.get("metadata", {}).get(
                "original_category"
            )
            if original_category:
                by_category.setdefault(original_category, []).append(override)

        # Compute override rate per category
        override_rates = {}
        for category in ["RECOGNIZE", "CODE", "ROUTE", "APPROVE"]:
            decisions = self.get_recent_decisions_by_category(
                category, lookback_days
            )
            overrides_for_cat = len(by_category.get(category, []))
            total = len(decisions)
            override_rates[category] = (
                overrides_for_cat / total if total > 0 else 0
            )

        return {
            "total_overrides": len(overrides),
            "lookback_days": lookback_days,
            "overrides_by_category": by_category,
            "override_rates_by_category": override_rates,
        }


# Singleton per church
_guider_feedback_stores: dict[str, GuiderFeedbackStore] = {}


def get_guider_feedback_store(church_id: str) -> GuiderFeedbackStore:
    """Get or create GuiderFeedbackStore singleton for a church."""
    if church_id not in _guider_feedback_stores:
        _guider_feedback_stores[church_id] = GuiderFeedbackStore(church_id)
    return _guider_feedback_stores[church_id]
