"""Phase 10: CardStore — unified persistence for Memory, Plan, Decision cards.

All cards stored as JSONL with optional SHA-256 chain immutability.
Supports queries by card_type, principal, period, created_at range.
"""

import json
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .schemas import Card


class CardStore:
    """Unified store for all card types with JSONL persistence and SHA-256 chain."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_file = self.data_dir / "cards.jsonl"
        self._ensure_store_exists()
        self._last_hash = None  # For SHA-256 chain

    def _ensure_store_exists(self):
        """Create empty store file if it doesn't exist."""
        if not self.store_file.exists():
            self.store_file.touch()

    def _compute_hash(self, card_dict: dict) -> str:
        """Compute SHA-256 hash of card data for chain immutability."""
        # Serialize deterministically (sorted keys, no whitespace)
        serialized = json.dumps(card_dict, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _compute_chain_hash(self, card_dict: dict, prior_hash: Optional[str]) -> str:
        """Compute chained hash: hash(current_card + prior_hash)."""
        # Clean dict first (no hash fields)
        clean_dict = {
            k: v for k, v in card_dict.items() if not k.startswith("_")
        }
        chain_input = clean_dict.copy()
        if prior_hash:
            chain_input['_prior_hash'] = prior_hash
        serialized = json.dumps(chain_input, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def write(self, card: Card, chain: bool = True) -> str:
        """Write a card to store.

        Args:
            card: Card instance (MemoryCard, PlanCard, DecisionPacket)
            chain: If True, include SHA-256 chain hash for immutability

        Returns:
            card_id
        """
        # Serialize card to dict (use model_dump with mode='json' for Pydantic v2)
        # This automatically converts Decimal to string
        card_dict = card.model_dump(mode='json')
        card_dict["created_at"] = card.created_at.isoformat()
        card_dict["updated_at"] = card.updated_at.isoformat()

        # Add hashes for immutability
        if chain:
            # Clean dict for hash (without hash fields)
            clean_dict = {
                k: v for k, v in card_dict.items() if not k.startswith("_")
            }
            card_dict["_hash"] = self._compute_hash(clean_dict)
            if self._last_hash:
                card_dict["_chain_hash"] = self._compute_chain_hash(
                    clean_dict, self._last_hash
                )
            self._last_hash = card_dict.get("_chain_hash", card_dict["_hash"])

        # Append to JSONL
        with open(self.store_file, "a") as f:
            f.write(json.dumps(card_dict) + "\n")

        return card.card_id

    def read(self, card_id: str) -> Optional[dict]:
        """Read a single card by card_id.

        Returns:
            Card dict (deserialized from JSONL) or None if not found
        """
        if not self.store_file.exists():
            return None

        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)
                if card_dict.get("card_id") == card_id:
                    return card_dict
        return None

    def query_by_type(self, card_type: str) -> list[dict]:
        """Get all cards of a specific type.

        Args:
            card_type: "memory", "plan", "decision"

        Returns:
            List of matching card dicts
        """
        results = []
        if not self.store_file.exists():
            return results

        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)
                if card_dict.get("card_type") == card_type:
                    results.append(card_dict)
        return results

    def query_by_principal(self, principal: str) -> list[dict]:
        """Get all cards created by a specific principal (agent/actor/cabinet member).

        Args:
            principal: actor_id or agent name

        Returns:
            List of matching card dicts
        """
        results = []
        if not self.store_file.exists():
            return results

        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)
                if card_dict.get("principal") == principal:
                    results.append(card_dict)
        return results

    def query_by_period(self, period: str) -> list[dict]:
        """Get all Plan Cards for a specific period.

        Args:
            period: "2026-05-11" or "2026-05-Q2"

        Returns:
            List of matching Plan Card dicts
        """
        results = []
        if not self.store_file.exists():
            return results

        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)
                if card_dict.get("card_type") == "plan" and card_dict.get("period") == period:
                    results.append(card_dict)
        return results

    def query_by_date_range(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict]:
        """Get all cards created within a date range.

        Args:
            start_dt: Start datetime
            end_dt: End datetime

        Returns:
            List of card dicts in chronological order
        """
        results = []
        if not self.store_file.exists():
            return results

        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)
                created_at_str = card_dict.get("created_at")
                if created_at_str:
                    created_at = datetime.fromisoformat(created_at_str)
                    if start_dt <= created_at <= end_dt:
                        results.append(card_dict)

        # Sort by created_at
        results.sort(key=lambda c: c.get("created_at", ""))
        return results

    def query_by_category(self, category: str) -> list[dict]:
        """Get all Decision Packets with a specific category.

        Args:
            category: RECOGNIZE, CODE, ROUTE, APPROVE, OVERRIDE, DISAVOW

        Returns:
            List of matching Decision Packet dicts
        """
        results = []
        if not self.store_file.exists():
            return results

        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)
                if (
                    card_dict.get("card_type") == "decision"
                    and card_dict.get("category") == category
                ):
                    results.append(card_dict)
        return results

    def verify_chain(self) -> bool:
        """Verify SHA-256 chain integrity.

        Returns:
            True if all chain hashes are valid, False otherwise
        """
        if not self.store_file.exists():
            return True

        prior_hash = None
        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)

                # Extract hash fields without modifying original
                stored_hash = card_dict.get("_hash")
                stored_chain_hash = card_dict.get("_chain_hash")

                # Create clean dict for hash computation (remove hash fields)
                clean_dict = {
                    k: v for k, v in card_dict.items() if not k.startswith("_")
                }

                computed_hash = self._compute_hash(clean_dict)
                if stored_hash and stored_hash != computed_hash:
                    return False

                if prior_hash:
                    computed_chain_hash = self._compute_chain_hash(
                        clean_dict, prior_hash
                    )
                    if stored_chain_hash and stored_chain_hash != computed_chain_hash:
                        return False

                prior_hash = stored_chain_hash or stored_hash

        return True

    def all_cards(self) -> list[dict]:
        """Get all cards in insertion order.

        Returns:
            List of all card dicts
        """
        results = []
        if not self.store_file.exists():
            return results

        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                results.append(json.loads(line))
        return results


# Singleton
_card_store: Optional[CardStore] = None


def get_card_store() -> CardStore:
    """Get or create CardStore singleton."""
    global _card_store
    if _card_store is None:
        data_dir = os.environ.get("EMBARK_CARD_JSONL_DIR", "backend/data/cards")
        _card_store = CardStore(data_dir)
    return _card_store
