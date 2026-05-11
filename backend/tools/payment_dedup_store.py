"""Payment deduplication store — Phase 9.

Tracks payment history for dedup detection and verdict gating.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from decimal import Decimal


class PaymentDedupStore:
    """Store payment history for deduplication detection."""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self.data_dir = Path(
            data_dir or os.environ.get(
                "EMBARK_CARD_JSONL_DIR",
                str(Path(__file__).resolve().parents[1] / "data" / "cards"),
            )
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _payment_history_file(self, church_id: str) -> Path:
        """Path to payment history JSONL for a church."""
        return self.data_dir / f"payment_history_{church_id}.jsonl"

    def record_payment(
        self,
        church_id: str,
        vendor: str,
        amount: Decimal,
        payment_date: datetime,
        reference_id: str,
        payment_method: str = "CHECK",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a payment in history."""
        record = {
            "church_id": church_id,
            "vendor": vendor,
            "amount": str(amount),
            "payment_date": payment_date.isoformat(),
            "reference_id": reference_id,
            "payment_method": payment_method,
            "recorded_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }

        file_path = self._payment_history_file(church_id)
        try:
            with file_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass  # Non-fatal: payment history recording failure doesn't block

    def get_payment_history(
        self,
        church_id: str,
        vendor: Optional[str] = None,
        amount: Optional[Decimal] = None,
        days_lookback: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get payment history matching criteria."""
        file_path = self._payment_history_file(church_id)
        if not file_path.exists():
            return []

        cutoff_date = datetime.utcnow() - timedelta(days=days_lookback)
        history = []

        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        # Filter by criteria
                        if vendor and record.get("vendor") != vendor:
                            continue
                        if amount and Decimal(record.get("amount", "0")) != amount:
                            continue

                        # Check date
                        payment_date = datetime.fromisoformat(record.get("payment_date", ""))
                        if payment_date < cutoff_date:
                            continue

                        # Add days_ago for convenience
                        days_ago = (datetime.utcnow() - payment_date).days
                        record["days_ago"] = days_ago
                        history.append(record)
                    except Exception:
                        continue
        except Exception:
            pass

        return history

    def is_exact_duplicate(
        self,
        church_id: str,
        vendor: str,
        amount: Decimal,
        payment_date: datetime,
        tolerance_hours: int = 24,
    ) -> bool:
        """Check if this is an exact duplicate of a recent payment."""
        history = self.get_payment_history(
            church_id,
            vendor=vendor,
            amount=amount,
            days_lookback=7,
        )

        cutoff_time = payment_date - timedelta(hours=tolerance_hours)
        for record in history:
            try:
                prior_date = datetime.fromisoformat(record.get("payment_date", ""))
                if cutoff_time <= prior_date <= payment_date:
                    return True
            except Exception:
                continue

        return False

    def find_probable_duplicates(
        self,
        church_id: str,
        vendor: str,
        amount: Decimal,
        days_lookback: int = 7,
    ) -> List[Dict[str, Any]]:
        """Find probable duplicate payments (same vendor + amount)."""
        return self.get_payment_history(
            church_id,
            vendor=vendor,
            amount=amount,
            days_lookback=days_lookback,
        )


# Singleton instance
_payment_dedup_store: Optional[PaymentDedupStore] = None


def get_payment_dedup_store() -> PaymentDedupStore:
    """Get or create singleton store."""
    global _payment_dedup_store
    if _payment_dedup_store is None:
        _payment_dedup_store = PaymentDedupStore()
    return _payment_dedup_store
