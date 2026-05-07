"""FR-05.1: approval chain configuration store + GL→chain resolver.

Approval chains are persisted as `backend/data/approval_chains_{church_id}.json`
holding a list of ApprovalChain objects. Pattern matching supports:

  - Exact match:   "6500"
  - Prefix wild:   "65*"          → matches "6500", "6512", "6599", ...
  - Range:         "6500-6600"    → inclusive numeric range

Lookup order: exact → range → wildcard. The first matching active chain wins.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from ..models.schemas import ApprovalChain

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _store_path(church_id: str) -> Path:
    return DATA_DIR / f"approval_chains_{church_id}.json"


def load_chains(church_id: str) -> List[ApprovalChain]:
    p = _store_path(church_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    chains: List[ApprovalChain] = []
    for row in raw:
        try:
            chains.append(ApprovalChain(**row))
        except Exception:
            # Skip malformed rows so a single bad entry doesn't break the file.
            continue
    return chains


def save_chains(church_id: str, chains: List[ApprovalChain]) -> None:
    p = _store_path(church_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [c.model_dump() for c in chains]
    p.write_text(json.dumps(payload, indent=2, default=str))


def add_chain(church_id: str, chain: ApprovalChain) -> List[ApprovalChain]:
    chains = load_chains(church_id)
    chains = [c for c in chains if c.chain_id != chain.chain_id]
    chains.append(chain)
    save_chains(church_id, chains)
    return chains


def remove_chain(church_id: str, chain_id: str) -> List[ApprovalChain]:
    chains = [c for c in load_chains(church_id) if c.chain_id != chain_id]
    save_chains(church_id, chains)
    return chains


def _gl_to_int(gl: str) -> Optional[int]:
    """Best-effort numeric coercion for range comparisons."""
    s = str(gl).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _matches_pattern(pattern: str, gl: str) -> bool:
    pat = pattern.strip()
    glx = str(gl).strip()
    if not pat or not glx:
        return False

    # Range "NNNN-MMMM"
    if "-" in pat and pat.count("-") == 1:
        lo_s, hi_s = pat.split("-", 1)
        lo, hi = _gl_to_int(lo_s), _gl_to_int(hi_s)
        target = _gl_to_int(glx)
        if lo is not None and hi is not None and target is not None:
            if lo > hi:
                lo, hi = hi, lo
            return lo <= target <= hi

    # Wildcard "65*" — prefix
    if pat.endswith("*"):
        prefix = pat[:-1]
        return glx.startswith(prefix)

    # Exact
    return pat == glx


def find_chain_for_gl(church_id: str, gl_account: str) -> Optional[ApprovalChain]:
    """Return the first matching active ApprovalChain for the given GL account.

    Resolution order: exact → range → wildcard. First active match wins.
    """
    chains = [c for c in load_chains(church_id) if c.active]
    if not chains:
        return None

    # Pass 1: exact
    for c in chains:
        p = c.gl_pattern.strip()
        if "-" in p or p.endswith("*"):
            continue
        if p == str(gl_account).strip():
            return c

    # Pass 2: range
    for c in chains:
        p = c.gl_pattern.strip()
        if "-" in p and not p.endswith("*"):
            if _matches_pattern(p, gl_account):
                return c

    # Pass 3: wildcard
    for c in chains:
        if c.gl_pattern.strip().endswith("*"):
            if _matches_pattern(c.gl_pattern, gl_account):
                return c

    return None
