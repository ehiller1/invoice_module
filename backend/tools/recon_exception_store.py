"""Reconciliation exception store — Phase 9.

Tracks unmatched transactions and bank reconciliation issues.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class ReconExceptionStore:
    """Store reconciliation exceptions (unmatched items, discrepancies)."""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self.data_dir = Path(
            data_dir or os.environ.get(
                "EMBARK_CARD_JSONL_DIR",
                str(Path(__file__).resolve().parents[1] / "data" / "cards"),
            )
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _exception_file(self, church_id: str) -> Path:
        """Path to exception JSONL for a church."""
        return self.data_dir / f"recon_exceptions_{church_id}.jsonl"

    def record_exception(
        self,
        church_id: str,
        exception_type: str,
        txn_id: str,
        amount: str,
        description: str,
        days_unmatched: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record a reconciliation exception.

        Args:
            exception_type: "BANK_ONLY", "ACS_ONLY", "AMOUNT_MISMATCH"
            txn_id: Bank transaction ID or ACS entry ID
            amount: Transaction amount
            description: Human-readable description
            days_unmatched: How long unmatched
            metadata: Additional context

        Returns:
            exception_id
        """
        exception_id = f"exc-{church_id}-{txn_id}-{datetime.utcnow().timestamp()}"

        record = {
            "exception_id": exception_id,
            "church_id": church_id,
            "exception_type": exception_type,
            "txn_id": txn_id,
            "amount": amount,
            "description": description,
            "days_unmatched": days_unmatched,
            "recorded_at": datetime.utcnow().isoformat(),
            "resolved": False,
            "resolution_notes": None,
            "metadata": metadata or {},
        }

        file_path = self._exception_file(church_id)
        try:
            with file_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass  # Non-fatal: exception recording doesn't block

        return exception_id

    def get_exceptions(
        self,
        church_id: str,
        resolved: Optional[bool] = None,
        exception_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get reconciliation exceptions for a church."""
        file_path = self._exception_file(church_id)
        if not file_path.exists():
            return []

        exceptions = []
        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if resolved is not None and record.get("resolved") != resolved:
                            continue
                        if exception_type and record.get("exception_type") != exception_type:
                            continue
                        exceptions.append(record)
                    except Exception:
                        continue
        except Exception:
            pass

        return exceptions

    def get_unresolved_exceptions(self, church_id: str) -> List[Dict[str, Any]]:
        """Get all unresolved exceptions."""
        return self.get_exceptions(church_id, resolved=False)

    def resolve_exception(
        self,
        church_id: str,
        exception_id: str,
        resolution_notes: str,
    ) -> bool:
        """Mark an exception as resolved."""
        file_path = self._exception_file(church_id)
        if not file_path.exists():
            return False

        updated = False
        try:
            lines = []
            with file_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()

            with file_path.open("w", encoding="utf-8") as f:
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("exception_id") == exception_id:
                            record["resolved"] = True
                            record["resolution_notes"] = resolution_notes
                            record["resolved_at"] = datetime.utcnow().isoformat()
                            updated = True
                        f.write(json.dumps(record) + "\n")
                    except Exception:
                        f.write(line + "\n")
        except Exception:
            pass

        return updated

    def get_exception_summary(self, church_id: str) -> Dict[str, Any]:
        """Get summary of exceptions by type."""
        exceptions = self.get_exceptions(church_id)
        unresolved = [e for e in exceptions if not e.get("resolved")]

        summary = {
            "church_id": church_id,
            "total_exceptions": len(exceptions),
            "unresolved_count": len(unresolved),
            "by_type": {},
            "oldest_unresolved_days": 0,
        }

        for exc in exceptions:
            exc_type = exc.get("exception_type", "UNKNOWN")
            if exc_type not in summary["by_type"]:
                summary["by_type"][exc_type] = {
                    "total": 0,
                    "unresolved": 0,
                }
            summary["by_type"][exc_type]["total"] += 1
            if not exc.get("resolved"):
                summary["by_type"][exc_type]["unresolved"] += 1

        if unresolved:
            oldest_days = max(e.get("days_unmatched", 0) for e in unresolved)
            summary["oldest_unresolved_days"] = oldest_days

        return summary


# Singleton instance
_recon_exception_store: Optional[ReconExceptionStore] = None


def get_recon_exception_store() -> ReconExceptionStore:
    """Get or create singleton store."""
    global _recon_exception_store
    if _recon_exception_store is None:
        _recon_exception_store = ReconExceptionStore()
    return _recon_exception_store
