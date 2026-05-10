"""Approval-chain + budgetary-authority persistence — PostgreSQL backend.

Replaces the JSON-backed `backend/tools/approval_chain_resolver.py` and
`backend/tools/budgetary_authority.py` storage layers. Pattern matching
for both kinds of rows stays in Python (so we can keep the
exact → range → wildcard precedence rules identical to the legacy code).

Schema reference:
- approval_chains (id PK, church_id FK, gl_pattern UNIQUE per church,
                   primary_approver_email/name, secondary_approver_email/name,
                   deadline_hours, escalation_days, is_active)
- budgetary_authorities (id PK, church_id FK, role, gl_pattern, max_amount,
                         can_override_restrictions, fund_restrictions [JSON])

Both `ApprovalChain.chain_id` and `BudgetaryAuthority.authority_id` are
opaque string ids; on read we synthesise them from the row's SERIAL
`id` ("ch_<id>" / "auth_<id>") so callers can round-trip.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from .connection import execute_query
from .transactions import atomic_transaction

from ..models.schemas import ApprovalChain, BudgetaryAuthority


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_church_pk(church_id: str) -> int:
    row = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True,
    )
    if row is None:
        raise ValueError(f"Unknown church_id: {church_id}")
    return int(row["id"])


def _row_to_chain(row: dict) -> ApprovalChain:
    return ApprovalChain(
        chain_id=f"ch_{int(row['id'])}",
        gl_pattern=row.get("gl_pattern") or "",
        primary_approver_email=row.get("primary_approver_email") or "",
        primary_approver_name=row.get("primary_approver_name") or "",
        secondary_approver_email=row.get("secondary_approver_email") or "",
        secondary_approver_name=row.get("secondary_approver_name") or "",
        deadline_hours=int(row.get("deadline_hours") or 48),
        escalation_days=int(row.get("escalation_days") or 5),
        active=bool(row.get("is_active") if row.get("is_active") is not None else True),
    )


def _row_to_authority(row: dict, church_id: str) -> BudgetaryAuthority:
    fund_restrictions: List[str] = []
    fr_raw = row.get("fund_restrictions")
    if fr_raw:
        if isinstance(fr_raw, list):
            fund_restrictions = [str(x) for x in fr_raw]
        else:
            try:
                parsed = json.loads(fr_raw)
                if isinstance(parsed, list):
                    fund_restrictions = [str(x) for x in parsed]
            except (json.JSONDecodeError, TypeError):
                fund_restrictions = []
    return BudgetaryAuthority(
        authority_id=f"auth_{int(row['id'])}",
        church_id=church_id,
        role=row.get("role") or "",
        gl_pattern=row.get("gl_pattern") or "",
        max_amount=float(row.get("max_amount") or 0.0),
        can_override_restrictions=bool(row.get("can_override_restrictions") or False),
        fund_restrictions=fund_restrictions,
        created_at=row.get("created_at") or datetime.utcnow(),
        updated_at=row.get("updated_at") or datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Pattern matching (kept in Python for parity with legacy resolver)
# ---------------------------------------------------------------------------

def _gl_to_int(gl: str) -> Optional[int]:
    s = str(gl or "").strip()
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
    if pat == "*":
        return True
    # Range "NNNN-MMMM" (and not also a wildcard)
    if "-" in pat and pat.count("-") == 1 and not pat.endswith("*"):
        lo_s, hi_s = pat.split("-", 1)
        lo, hi = _gl_to_int(lo_s), _gl_to_int(hi_s)
        target = _gl_to_int(glx)
        if lo is not None and hi is not None and target is not None:
            if lo > hi:
                lo, hi = hi, lo
            return lo <= target <= hi
        return False
    if pat.endswith("*"):
        return glx.startswith(pat[:-1])
    return pat == glx


# ===========================================================================
# Approval chains
# ===========================================================================

def load_chains(church_id: str) -> List[ApprovalChain]:
    """Load every approval chain for a church."""
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT id, gl_pattern,
               primary_approver_email, primary_approver_name,
               secondary_approver_email, secondary_approver_name,
               deadline_hours, escalation_days, is_active
        FROM approval_chains
        WHERE church_id = %s
        ORDER BY gl_pattern
        """,
        (church_pk,),
    ) or []
    return [_row_to_chain(r) for r in rows]


def add_chain(church_id: str, chain: ApprovalChain) -> ApprovalChain:
    """Insert or update an approval chain by (church, gl_pattern)."""
    church_pk = _resolve_church_pk(church_id)
    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO approval_chains (
                church_id, gl_pattern,
                primary_approver_email, primary_approver_name,
                secondary_approver_email, secondary_approver_name,
                deadline_hours, escalation_days, is_active, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (church_id, gl_pattern) DO UPDATE SET
                primary_approver_email   = EXCLUDED.primary_approver_email,
                primary_approver_name    = EXCLUDED.primary_approver_name,
                secondary_approver_email = EXCLUDED.secondary_approver_email,
                secondary_approver_name  = EXCLUDED.secondary_approver_name,
                deadline_hours           = EXCLUDED.deadline_hours,
                escalation_days          = EXCLUDED.escalation_days,
                is_active                = EXCLUDED.is_active,
                updated_at               = CURRENT_TIMESTAMP
            RETURNING id, gl_pattern, primary_approver_email, primary_approver_name,
                      secondary_approver_email, secondary_approver_name,
                      deadline_hours, escalation_days, is_active
            """,
            (
                church_pk,
                chain.gl_pattern,
                chain.primary_approver_email,
                chain.primary_approver_name,
                chain.secondary_approver_email,
                chain.secondary_approver_name,
                int(chain.deadline_hours),
                int(chain.escalation_days),
                bool(chain.active),
            ),
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        cur.close()
    return _row_to_chain(row)


def save_chains(church_id: str, chains: List[ApprovalChain]) -> None:
    """Replace every approval chain for a church."""
    church_pk = _resolve_church_pk(church_id)
    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM approval_chains WHERE church_id = %s", (church_pk,))
        for c in chains:
            cur.execute(
                """
                INSERT INTO approval_chains (
                    church_id, gl_pattern,
                    primary_approver_email, primary_approver_name,
                    secondary_approver_email, secondary_approver_name,
                    deadline_hours, escalation_days, is_active, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    church_pk,
                    c.gl_pattern,
                    c.primary_approver_email,
                    c.primary_approver_name,
                    c.secondary_approver_email,
                    c.secondary_approver_name,
                    int(c.deadline_hours),
                    int(c.escalation_days),
                    bool(c.active),
                ),
            )
        cur.close()


def remove_chain(church_id: str, gl_pattern: str) -> None:
    """Delete the chain identified by gl_pattern."""
    church_pk = _resolve_church_pk(church_id)
    execute_query(
        "DELETE FROM approval_chains WHERE church_id = %s AND gl_pattern = %s",
        (church_pk, gl_pattern),
    )


def find_chain_for_gl(church_id: str, account_number: str) -> Optional[ApprovalChain]:
    """Return the first matching active chain for a GL account.

    Resolution order: exact → range → wildcard. First active match wins.
    """
    chains = [c for c in load_chains(church_id) if c.active]
    if not chains:
        return None

    # Pass 1: exact
    for c in chains:
        p = c.gl_pattern.strip()
        if "-" in p or p.endswith("*") or p == "*":
            continue
        if p == str(account_number).strip():
            return c

    # Pass 2: range
    for c in chains:
        p = c.gl_pattern.strip()
        if "-" in p and not p.endswith("*") and p != "*":
            if _matches_pattern(p, account_number):
                return c

    # Pass 3: wildcard
    for c in chains:
        p = c.gl_pattern.strip()
        if p == "*" or p.endswith("*"):
            if _matches_pattern(p, account_number):
                return c

    return None


# ===========================================================================
# Budgetary authorities
# ===========================================================================

def load_budgetary_authorities(church_id: str) -> List[BudgetaryAuthority]:
    """Load every authority for a church."""
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT id, role, gl_pattern, max_amount, can_override_restrictions,
               fund_restrictions, created_at, updated_at
        FROM budgetary_authorities
        WHERE church_id = %s
        ORDER BY role, gl_pattern
        """,
        (church_pk,),
    ) or []
    return [_row_to_authority(r, church_id) for r in rows]


def add_authority(church_id: str, authority: BudgetaryAuthority) -> BudgetaryAuthority:
    """Insert or update an authority.

    The relational schema lacks a UNIQUE constraint distinguishing rows, so
    we treat (church_id, role, gl_pattern) as the natural key: existing rows
    matching that triple are updated; otherwise a new row is inserted.
    """
    church_pk = _resolve_church_pk(church_id)
    fr_json = json.dumps(authority.fund_restrictions or [])
    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM budgetary_authorities
            WHERE church_id = %s AND role = %s AND gl_pattern = %s
            LIMIT 1
            """,
            (church_pk, authority.role, authority.gl_pattern),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """
                UPDATE budgetary_authorities
                   SET max_amount = %s,
                       can_override_restrictions = %s,
                       fund_restrictions = %s,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = %s
                RETURNING id, role, gl_pattern, max_amount,
                          can_override_restrictions, fund_restrictions,
                          created_at, updated_at
                """,
                (
                    float(authority.max_amount),
                    bool(authority.can_override_restrictions),
                    fr_json,
                    int(existing[0]),
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO budgetary_authorities (
                    church_id, role, gl_pattern, max_amount,
                    can_override_restrictions, fund_restrictions, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING id, role, gl_pattern, max_amount,
                          can_override_restrictions, fund_restrictions,
                          created_at, updated_at
                """,
                (
                    church_pk,
                    authority.role,
                    authority.gl_pattern,
                    float(authority.max_amount),
                    bool(authority.can_override_restrictions),
                    fr_json,
                ),
            )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        cur.close()
    return _row_to_authority(row, church_id)


def update_authority(church_id: str, authority_id: str, updates: dict) -> None:
    """Update specific fields of an authority by its synthesised id ("auth_<n>")."""
    church_pk = _resolve_church_pk(church_id)
    if not authority_id.startswith("auth_"):
        raise ValueError(f"Unrecognised authority_id format: {authority_id!r}")
    try:
        pk = int(authority_id.split("_", 1)[1])
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid authority_id: {authority_id!r}") from e

    field_map = {
        "role": "role",
        "gl_pattern": "gl_pattern",
        "max_amount": "max_amount",
        "can_override_restrictions": "can_override_restrictions",
        "fund_restrictions": "fund_restrictions",
    }
    sets: List[str] = []
    params: List = []
    for k, v in (updates or {}).items():
        col = field_map.get(k)
        if col is None:
            continue
        if col == "fund_restrictions":
            sets.append(f"{col} = %s")
            params.append(json.dumps(v or []))
        elif col == "max_amount":
            sets.append(f"{col} = %s")
            params.append(float(v))
        elif col == "can_override_restrictions":
            sets.append(f"{col} = %s")
            params.append(bool(v))
        else:
            sets.append(f"{col} = %s")
            params.append(v)
    if not sets:
        return
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.extend([pk, church_pk])
    execute_query(
        f"""
        UPDATE budgetary_authorities
           SET {', '.join(sets)}
         WHERE id = %s AND church_id = %s
        """,
        tuple(params),
    )


def remove_authority(church_id: str, authority_id: str) -> None:
    """Delete an authority by synthesised id ("auth_<n>")."""
    church_pk = _resolve_church_pk(church_id)
    if not authority_id.startswith("auth_"):
        raise ValueError(f"Unrecognised authority_id format: {authority_id!r}")
    try:
        pk = int(authority_id.split("_", 1)[1])
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid authority_id: {authority_id!r}") from e
    execute_query(
        "DELETE FROM budgetary_authorities WHERE id = %s AND church_id = %s",
        (pk, church_pk),
    )


def save_authorities(church_id: str, authorities: List[BudgetaryAuthority]) -> None:
    """Replace every authority for a church."""
    church_pk = _resolve_church_pk(church_id)
    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM budgetary_authorities WHERE church_id = %s",
            (church_pk,),
        )
        for a in authorities:
            cur.execute(
                """
                INSERT INTO budgetary_authorities (
                    church_id, role, gl_pattern, max_amount,
                    can_override_restrictions, fund_restrictions, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    church_pk,
                    a.role,
                    a.gl_pattern,
                    float(a.max_amount),
                    bool(a.can_override_restrictions),
                    json.dumps(a.fund_restrictions or []),
                ),
            )
        cur.close()
