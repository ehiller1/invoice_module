"""Phase 10: Decision Ledger with SHA-256 Chain Immutability.

Extends backend.decision_ledger with:
- SHA-256 chain for immutability verification
- Categorization tags (Phase 10.5-10.6)
- Guider confidence learning from ledger
"""

import json
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from backend.decision_ledger import (
    DecisionCategory,
    LedgerEntry,
)


class DecisionLedgerWithChain:
    """Decision Ledger with SHA-256 chain and governance extensions.

    Immutable append-only ledger with chained hashes for audit trail integrity.
    Supports governance categorization tags (Phase 10.5-10.6).
    """

    def __init__(self, church_id: str, data_dir: str):
        self.church_id = church_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.data_dir / f"{church_id}_ledger.jsonl"
        self._ensure_ledger_exists()
        self._last_hash = None

    def _ensure_ledger_exists(self):
        """Create empty ledger file if it doesn't exist."""
        if not self.ledger_file.exists():
            self.ledger_file.touch()

    def _compute_hash(self, entry_dict: dict) -> str:
        """Compute SHA-256 hash of ledger entry."""
        # Remove hash fields before computing
        clean_dict = {k: v for k, v in entry_dict.items() if not k.startswith("_")}
        serialized = json.dumps(clean_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _compute_chain_hash(self, entry_dict: dict, prior_hash: Optional[str]) -> str:
        """Compute chained hash: hash(entry + prior_hash)."""
        clean_dict = {k: v for k, v in entry_dict.items() if not k.startswith("_")}
        chain_input = {"entry": clean_dict}
        if prior_hash:
            chain_input["prior_hash"] = prior_hash
        serialized = json.dumps(chain_input, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def append(
        self,
        entry: LedgerEntry,
        categorization_tags: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        """Append an immutable ledger entry.

        Args:
            entry: LedgerEntry to append
            categorization_tags: Phase 10.5-10.6 governance tags

        Returns:
            entry_id of appended entry
        """
        entry_dict = entry.model_dump()
        entry_dict["timestamp"] = entry.timestamp.isoformat()

        # Add categorization tags
        if categorization_tags:
            entry_dict["categorization_tags"] = categorization_tags

        # Compute hashes for chain immutability
        entry_dict["_hash"] = self._compute_hash(entry_dict)
        if self._last_hash:
            entry_dict["_chain_hash"] = self._compute_chain_hash(
                entry_dict, self._last_hash
            )
            entry_dict["_prior_hash"] = self._last_hash

        # Update last hash for next entry
        self._last_hash = entry_dict.get("_chain_hash", entry_dict["_hash"])

        # Append to JSONL
        with open(self.ledger_file, "a") as f:
            f.write(json.dumps(entry_dict) + "\n")

        return entry.entry_id

    def find_by_decision(self, decision_id: str) -> list[dict]:
        """Find all ledger entries for a decision."""
        results = []
        if not self.ledger_file.exists():
            return results

        with open(self.ledger_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry_dict = json.loads(line)
                if entry_dict.get("decision_id") == decision_id:
                    results.append(entry_dict)
        return results

    def find_by_actor(
        self, actor_id: str, after: Optional[datetime] = None
    ) -> list[dict]:
        """Find all decisions by an actor (audit trail)."""
        results = []
        if not self.ledger_file.exists():
            return results

        with open(self.ledger_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry_dict = json.loads(line)
                if entry_dict.get("authoring_actor", {}).get("actor_id") == actor_id:
                    if after:
                        ts_str = entry_dict.get("timestamp")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str)
                            if ts >= after:
                                results.append(entry_dict)
                    else:
                        results.append(entry_dict)
        return results

    def find_by_category(
        self, category: str, period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None
    ) -> list[dict]:
        """Find decisions by category (Phase 10.5-10.6).

        Args:
            category: RECOGNIZE, CODE, ROUTE, APPROVE, OVERRIDE, DISAVOW
            period_start: Filter by date range (start)
            period_end: Filter by date range (end)

        Returns:
            List of matching ledger entries
        """
        results = []
        if not self.ledger_file.exists():
            return results

        with open(self.ledger_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry_dict = json.loads(line)
                if entry_dict.get("category") == category:
                    if period_start or period_end:
                        ts_str = entry_dict.get("timestamp")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str)
                            if period_start and ts < period_start:
                                continue
                            if period_end and ts > period_end:
                                continue
                    results.append(entry_dict)
        return results

    def find_overrides(self) -> list[dict]:
        """Find all override decisions."""
        results = []
        if not self.ledger_file.exists():
            return results

        with open(self.ledger_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry_dict = json.loads(line)
                if entry_dict.get("category") == DecisionCategory.OVERRIDE.value:
                    results.append(entry_dict)
        return results

    def find_by_confidence(
        self, min_confidence: float = 0.5
    ) -> list[dict]:
        """Find decisions meeting confidence threshold (Phase 10.5-10.6).

        Args:
            min_confidence: Minimum confidence (0.0-1.0)

        Returns:
            List of high-confidence decisions
        """
        results = []
        if not self.ledger_file.exists():
            return results

        with open(self.ledger_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry_dict = json.loads(line)
                # Check confidence in metadata
                metadata = entry_dict.get("metadata", {})
                if isinstance(metadata, dict):
                    confidence = metadata.get("confidence", 0.5)
                    if confidence >= min_confidence:
                        results.append(entry_dict)
        return results

    def verify_chain(self) -> bool:
        """Verify SHA-256 chain integrity.

        Returns:
            True if all chain hashes are valid, False otherwise
        """
        if not self.ledger_file.exists():
            return True

        prior_hash = None
        with open(self.ledger_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry_dict = json.loads(line)

                # Verify entry hash
                stored_hash = entry_dict.get("_hash")
                stored_chain_hash = entry_dict.get("_chain_hash")

                computed_hash = self._compute_hash(entry_dict)
                if stored_hash and stored_hash != computed_hash:
                    return False

                if prior_hash:
                    computed_chain_hash = self._compute_chain_hash(
                        entry_dict, prior_hash
                    )
                    if (
                        stored_chain_hash
                        and stored_chain_hash != computed_chain_hash
                    ):
                        return False

                prior_hash = stored_chain_hash or stored_hash

        return True

    def all_entries(self) -> list[dict]:
        """Get all entries in insertion order."""
        results = []
        if not self.ledger_file.exists():
            return results

        with open(self.ledger_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                results.append(json.loads(line))
        return results


# Singleton instances per church_id
_ledger_instances: dict[str, DecisionLedgerWithChain] = {}


def get_decision_ledger(church_id: str) -> DecisionLedgerWithChain:
    """Get or create DecisionLedger singleton for a church."""
    if church_id not in _ledger_instances:
        data_dir = os.environ.get("EMBARK_CARD_JSONL_DIR", "backend/data/cards")
        _ledger_instances[church_id] = DecisionLedgerWithChain(church_id, data_dir)
    return _ledger_instances[church_id]
