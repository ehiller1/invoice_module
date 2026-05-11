"""Phase 10: CardStore — unified persistence for Memory, Plan, Decision cards.

All cards stored as JSONL with optional SHA-256 chain immutability.
Supports queries by card_type, principal, period, created_at range.
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .schemas import Card
from .chain import compute_hash, compute_chain_hash, verify_chain


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
        return compute_hash(card_dict)

    def _compute_chain_hash(self, card_dict: dict, prior_hash: Optional[str]) -> str:
        """Compute chained hash: hash(current_card + prior_hash)."""
        return compute_chain_hash(card_dict, prior_hash)

    def write(self, card: Card, chain: bool = True, prior_hash: Optional[str] = None) -> str:
        """Write a card to store with optional concurrent write protection.

        Args:
            card: Card instance (MemoryCard, PlanCard, DecisionPacket)
            chain: If True, include SHA-256 chain hash for immutability
            prior_hash: Expected prior hash for optimistic locking (detects concurrent writes)

        Returns:
            card_id

        Raises:
            ValueError: If prior_hash is provided and doesn't match current chain state
        """
        # Serialize card to dict (use model_dump with mode='json' for Pydantic v2)
        # This automatically converts Decimal to string
        card_dict = card.model_dump(mode='json')
        card_dict["created_at"] = card.created_at.isoformat()
        card_dict["updated_at"] = card.updated_at.isoformat()

        # Concurrent write protection: verify expected prior hash
        if chain and prior_hash and self._last_hash != prior_hash:
            raise ValueError(
                f"Concurrent write detected: expected prior_hash {prior_hash}, "
                f"but current chain state is {self._last_hash}"
            )

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
                card_dict["_prior_hash"] = self._last_hash
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

    def detect_concurrent_writes(self) -> list[dict]:
        """Detect entries with broken chain continuity (concurrent writes).

        Returns:
            List of entries where _prior_hash doesn't match previous entry's hash
        """
        anomalies = []
        if not self.store_file.exists():
            return anomalies

        prior_hash = None
        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)
                stored_prior_hash = card_dict.get("_prior_hash")

                # Check if _prior_hash matches our expected chain state
                if stored_prior_hash and prior_hash and stored_prior_hash != prior_hash:
                    anomalies.append({
                        "card_id": card_dict.get("card_id"),
                        "expected_prior_hash": prior_hash,
                        "stored_prior_hash": stored_prior_hash,
                        "concurrent_write": True,
                    })

                # Update prior hash for next iteration
                prior_hash = card_dict.get("_chain_hash") or card_dict.get("_hash")

        return anomalies

    def get_current_chain_hash(self) -> Optional[str]:
        """Get the current chain hash (hash of last card written).

        Returns:
            Current chain hash or None if store is empty
        """
        if not self.store_file.exists():
            return None

        last_hash = None
        with open(self.store_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                card_dict = json.loads(line)
                last_hash = card_dict.get("_chain_hash") or card_dict.get("_hash")

        return last_hash

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

    def query_by_tags(self, tags: list[str]) -> list[dict]:
        """Get all cards with any of the specified tags in metadata.

        Args:
            tags: List of tag strings to search for (OR logic)

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
                card_tags = card_dict.get("metadata", {}).get("tags", [])
                # Check if any of the requested tags are present
                if any(tag in card_tags for tag in tags):
                    results.append(card_dict)
        return results

    def query_by_metadata(self, field: str, value: any) -> list[dict]:
        """Get all cards where a metadata field matches a value.

        Args:
            field: Metadata field name (e.g., "pledge_id", "policy_id", "principal")
            value: Value to match (exact match)

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
                metadata = card_dict.get("metadata", {})
                if metadata.get(field) == value:
                    results.append(card_dict)
        return results

    # ── Async-safe I/O (use these from async endpoints) ─────────────────────

    def _read_all_sync(self) -> list[dict]:
        """Read every JSONL line into a list. Runs in a thread via run_in_executor."""
        if not self.store_file.exists():
            return []
        result = []
        with open(self.store_file, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        result.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return result

    async def aquery_by_principal(self, principal: str) -> list[dict]:
        """Async, non-blocking version of query_by_principal."""
        loop = asyncio.get_event_loop()
        all_cards = await loop.run_in_executor(None, self._read_all_sync)
        return [c for c in all_cards if c.get("principal") == principal]

    async def aread(self, card_id: str) -> Optional[dict]:
        """Async, non-blocking version of read."""
        loop = asyncio.get_event_loop()
        all_cards = await loop.run_in_executor(None, self._read_all_sync)
        for c in all_cards:
            if c.get("card_id") == card_id:
                return c
        return None


# Singleton
_card_store: Optional[CardStore] = None


def get_card_store() -> CardStore:
    """Get or create CardStore singleton."""
    global _card_store
    if _card_store is None:
        data_dir = os.environ.get("EMBARK_CARD_JSONL_DIR", "backend/data/cards")
        _card_store = CardStore(data_dir)
    return _card_store
