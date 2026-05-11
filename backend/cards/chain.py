"""SHA-256 Chain Utilities — Unified hash computation for Card Store and Decision Ledger.

This module provides deterministic, chain-verifiable hashing for audit trails.
All hashing uses the same serialization format to ensure cross-system verification.
"""

import hashlib
import json
from typing import Optional


def compute_hash(data: dict) -> str:
    """
    Compute SHA-256 hash of data for integrity verification.

    Serializes with sorted keys and no whitespace to ensure determinism.

    Args:
        data: Dictionary to hash

    Returns:
        Hex-encoded SHA-256 digest
    """
    serialized = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode()).hexdigest()


def compute_chain_hash(data: dict, prior_hash: Optional[str] = None) -> str:
    """
    Compute chained hash: hash(current + prior_hash).

    This creates an immutable chain where each entry depends on all prior entries.
    The chain is broken if any prior entry is modified or reordered.

    Serialization format (canonical):
    - Remove underscore-prefixed fields (e.g., _hash, _chain_hash)
    - Sort keys alphabetically
    - Include prior_hash as 'prior_hash' field if present
    - No whitespace

    Args:
        data: Dictionary to hash (will clean underscore fields)
        prior_hash: Previous entry's chain hash (if part of chain)

    Returns:
        Hex-encoded SHA-256 digest of chained entry
    """
    # Clean dict: remove internal fields like _hash, _chain_hash, _prior_hash
    clean_dict = {k: v for k, v in data.items() if not k.startswith("_")}

    # Build chain input
    chain_input = clean_dict.copy()
    if prior_hash:
        chain_input["prior_hash"] = prior_hash

    # Compute deterministic hash
    serialized = json.dumps(chain_input, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode()).hexdigest()


def verify_chain(entries: list[dict], start_hash: Optional[str] = None) -> bool:
    """
    Verify SHA-256 chain integrity for a sequence of entries.

    Recomputes each entry's chain hash and verifies it matches the stored hash.
    Returns False if any entry is modified, missing, or out of order.

    Args:
        entries: List of card/entry dicts (must be in order)
        start_hash: Optional prior hash to verify the first entry against

    Returns:
        True if all hashes match and chain is intact, False otherwise
    """
    prior = start_hash
    for entry in entries:
        stored_hash = entry.get("chain_hash") or entry.get("_chain_hash")
        if not stored_hash:
            # No hash stored; cannot verify
            return False

        computed = compute_chain_hash(entry, prior)
        if computed != stored_hash:
            return False

        prior = stored_hash

    return True
