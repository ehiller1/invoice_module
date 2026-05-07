"""FR-NF-Authority: Budgetary Authority Routing Matrix.

Maps roles -> (GL pattern, max amount, fund restrictions, override flag).

Used by the Step 7a+ check to verify a primary approver actually has authority
to approve a given GL line at a given amount, in a given fund.

Persists per church to `backend/data/authorities_{church_id}.json`.

Pattern matching is identical to the approval-chain resolver:
  - Exact:     "6500"
  - Range:     "6500-6600"      (inclusive numeric range)
  - Wildcard:  "65*" or "*"     (prefix; "*" matches every GL)

Resolution order: exact -> range -> wildcard. First active match wins.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from ..models.schemas import BudgetaryAuthority

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ===== Storage =====

def _store_path(church_id: str) -> Path:
    return DATA_DIR / f"authorities_{church_id}.json"


def load_authorities(church_id: str) -> List[BudgetaryAuthority]:
    p = _store_path(church_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    rows: List[BudgetaryAuthority] = []
    for row in raw:
        try:
            rows.append(BudgetaryAuthority(**row))
        except Exception:
            continue
    return rows


def save_authorities(church_id: str, authorities: List[BudgetaryAuthority]) -> None:
    p = _store_path(church_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [a.model_dump() for a in authorities]
    p.write_text(json.dumps(payload, indent=2, default=str))


def add_authority(church_id: str, authority: BudgetaryAuthority) -> List[BudgetaryAuthority]:
    rows = load_authorities(church_id)
    rows = [a for a in rows if a.authority_id != authority.authority_id]
    rows.append(authority)
    save_authorities(church_id, rows)
    return rows


def update_authority(church_id: str, authority_id: str, updates: dict) -> Optional[BudgetaryAuthority]:
    rows = load_authorities(church_id)
    found: Optional[BudgetaryAuthority] = None
    for i, a in enumerate(rows):
        if a.authority_id == authority_id:
            data = a.model_dump()
            data.update(updates)
            data["authority_id"] = authority_id
            data["updated_at"] = datetime.utcnow()
            try:
                rows[i] = BudgetaryAuthority(**data)
                found = rows[i]
            except Exception:
                return None
            break
    if found:
        save_authorities(church_id, rows)
    return found


def remove_authority(church_id: str, authority_id: str) -> List[BudgetaryAuthority]:
    rows = [a for a in load_authorities(church_id) if a.authority_id != authority_id]
    save_authorities(church_id, rows)
    return rows


# ===== Pattern matching =====

def _gl_to_int(gl: str) -> Optional[int]:
    s = str(gl).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _matches_pattern(pattern: str, gl: str) -> bool:
    pat = (pattern or "").strip()
    glx = str(gl or "").strip()
    if not pat or not glx:
        return False

    # Wildcard "*" — matches everything
    if pat == "*":
        return True

    # Range "NNNN-MMMM"
    if "-" in pat and pat.count("-") == 1 and not pat.endswith("*"):
        lo_s, hi_s = pat.split("-", 1)
        lo, hi = _gl_to_int(lo_s), _gl_to_int(hi_s)
        target = _gl_to_int(glx)
        if lo is not None and hi is not None and target is not None:
            if lo > hi:
                lo, hi = hi, lo
            return lo <= target <= hi
        return False

    # Wildcard "65*"
    if pat.endswith("*"):
        prefix = pat[:-1]
        return glx.startswith(prefix)

    # Exact
    return pat == glx


# ===== Authority check =====

def get_authority_for_role_and_gl(
    church_id: str,
    role: str,
    gl_code: str,
    fund: str,
    amount: float,
) -> Tuple[Optional[BudgetaryAuthority], str]:
    """Check if `role` can approve `gl_code` at `amount` from `fund`.

    Resolution order: exact -> range -> wildcard. First match within role,
    fund-restriction, and amount-cap wins. Returns (authority_or_None, reason).
    """
    rows = [a for a in load_authorities(church_id) if a.role == role]
    if not rows:
        return None, f"No authority configured for role '{role}'"

    # Filter by GL pattern match — collect candidates by precedence class.
    exact_matches: List[BudgetaryAuthority] = []
    range_matches: List[BudgetaryAuthority] = []
    wildcard_matches: List[BudgetaryAuthority] = []

    for a in rows:
        pat = (a.gl_pattern or "").strip()
        if not pat:
            continue
        if pat == "*" or pat.endswith("*"):
            if _matches_pattern(pat, gl_code):
                wildcard_matches.append(a)
        elif "-" in pat and pat.count("-") == 1:
            if _matches_pattern(pat, gl_code):
                range_matches.append(a)
        else:
            if _matches_pattern(pat, gl_code):
                exact_matches.append(a)

    candidates = exact_matches + range_matches + wildcard_matches
    if not candidates:
        return None, (
            f"No matching GL pattern for role '{role}' and GL '{gl_code}'"
        )

    last_reason = ""
    for a in candidates:
        # Amount cap
        try:
            cap = float(a.max_amount)
        except Exception:
            cap = 0.0
        if float(amount) > cap:
            last_reason = (
                f"Amount ${amount:,.2f} exceeds max ${cap:,.2f} for role '{role}'"
            )
            continue

        # Fund restriction
        if a.fund_restrictions and fund not in a.fund_restrictions:
            last_reason = (
                f"Fund '{fund}' not in allowed list "
                f"{a.fund_restrictions} for role '{role}'"
            )
            continue

        return a, ""

    return None, last_reason or "No authority satisfied amount/fund constraints"


def can_override_restriction(church_id: str, role: str, gl_code: str) -> bool:
    """Return True if any authority for (role, gl_code) sets `can_override_restrictions`."""
    rows = [
        a for a in load_authorities(church_id)
        if a.role == role and a.can_override_restrictions
    ]
    for a in rows:
        if _matches_pattern(a.gl_pattern, gl_code):
            return True
    return False
