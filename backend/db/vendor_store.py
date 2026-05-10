"""Vendor master persistence — PostgreSQL backend.

Replaces the JSON-backed `backend/tools/vendor_store.py`. Vendors are
keyed by (church_id, name) per the schema's UNIQUE constraint. The
`Vendor` Pydantic model carries an opaque `vendor_id` we synthesise from
the row's SERIAL `id` ("v_<id>") on read.

Schema reference:
- vendors (id PK, church_id FK, name UNIQUE per church,
           ach_routing, ach_account_enc, ach_account_last4,
           address, w9_on_file, notes)

Fuzzy matching uses PostgreSQL `pg_trgm` similarity when the extension
is available; otherwise it falls back to ILIKE substring matching.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .connection import execute_query
from .transactions import atomic_transaction

from ..models.schemas import Vendor


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


_PG_TRGM_AVAILABLE: Optional[bool] = None


def _ensure_pg_trgm() -> bool:
    """Try to enable pg_trgm extension. Returns True on success/already enabled."""
    global _PG_TRGM_AVAILABLE
    if _PG_TRGM_AVAILABLE is not None:
        return _PG_TRGM_AVAILABLE
    try:
        execute_query("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        _PG_TRGM_AVAILABLE = True
    except Exception:
        _PG_TRGM_AVAILABLE = False
    return _PG_TRGM_AVAILABLE


def _row_to_vendor(row: dict, church_id: str) -> Vendor:
    return Vendor(
        vendor_id=f"v_{int(row['id'])}",
        church_id=church_id,
        name=row["name"],
        ach_routing=row.get("ach_routing"),
        ach_account_enc=row.get("ach_account_enc"),
        ach_account_last4=row.get("ach_account_last4"),
        address=row.get("address"),
        w9_on_file=bool(row.get("w9_on_file") or False),
        notes=row.get("notes"),
    )


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_vendors(church_id: str) -> List[Vendor]:
    """Load every vendor for a church, ordered by name."""
    church_pk = _resolve_church_pk(church_id)
    rows = execute_query(
        """
        SELECT id, name, ach_routing, ach_account_enc, ach_account_last4,
               address, w9_on_file, notes
        FROM vendors
        WHERE church_id = %s
        ORDER BY name
        """,
        (church_pk,),
    ) or []
    return [_row_to_vendor(r, church_id) for r in rows]


def upsert_vendor(church_id: str, vendor: Vendor) -> Vendor:
    """Insert or update a vendor by (church, name). Returns the persisted Vendor."""
    church_pk = _resolve_church_pk(church_id)
    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vendors (
                church_id, name, ach_routing, ach_account_enc, ach_account_last4,
                address, w9_on_file, notes, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (church_id, name) DO UPDATE SET
                ach_routing       = EXCLUDED.ach_routing,
                ach_account_enc   = EXCLUDED.ach_account_enc,
                ach_account_last4 = EXCLUDED.ach_account_last4,
                address           = EXCLUDED.address,
                w9_on_file        = EXCLUDED.w9_on_file,
                notes             = EXCLUDED.notes,
                updated_at        = CURRENT_TIMESTAMP
            RETURNING id, name, ach_routing, ach_account_enc, ach_account_last4,
                      address, w9_on_file, notes
            """,
            (
                church_pk,
                vendor.name,
                vendor.ach_routing,
                vendor.ach_account_enc,
                vendor.ach_account_last4,
                vendor.address,
                bool(vendor.w9_on_file),
                vendor.notes,
            ),
        )
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        cur.close()
    return _row_to_vendor(row, church_id)


def find_vendor_by_name(
    church_id: str,
    name: str,
    fuzzy: bool = True,
    similarity_threshold: float = 0.4,
) -> Optional[Vendor]:
    """Find a vendor by name.

    Strategy:
      1. Exact case-insensitive match.
      2. If `fuzzy` and pg_trgm is available, use trigram similarity.
      3. Otherwise fall back to normalised-substring matching in Python.
    """
    if not name or not name.strip():
        return None
    church_pk = _resolve_church_pk(church_id)

    # 1. Exact (case-insensitive)
    row = execute_query(
        """
        SELECT id, name, ach_routing, ach_account_enc, ach_account_last4,
               address, w9_on_file, notes
        FROM vendors
        WHERE church_id = %s AND LOWER(name) = LOWER(%s)
        LIMIT 1
        """,
        (church_pk, name),
        fetch_one=True,
    )
    if row:
        return _row_to_vendor(row, church_id)

    if not fuzzy:
        return None

    # 2. pg_trgm similarity
    if _ensure_pg_trgm():
        try:
            row = execute_query(
                """
                SELECT id, name, ach_routing, ach_account_enc, ach_account_last4,
                       address, w9_on_file, notes,
                       similarity(name, %s) AS sim
                FROM vendors
                WHERE church_id = %s
                  AND similarity(name, %s) >= %s
                ORDER BY sim DESC
                LIMIT 1
                """,
                (name, church_pk, name, similarity_threshold),
                fetch_one=True,
            )
            if row:
                return _row_to_vendor(row, church_id)
        except Exception:
            pass  # fall through to Python fallback

    # 3. Python fallback: normalized substring
    target = _normalize(name)
    if not target:
        return None
    for v in load_vendors(church_id):
        nv = _normalize(v.name)
        if not nv:
            continue
        if nv == target or nv.startswith(target) or target.startswith(nv):
            return v
        if nv in target or target in nv:
            return v
    return None


def delete_vendor(church_id: str, vendor_name: str) -> None:
    """Delete a vendor by name."""
    church_pk = _resolve_church_pk(church_id)
    execute_query(
        "DELETE FROM vendors WHERE church_id = %s AND name = %s",
        (church_pk, vendor_name),
    )


def save_vendors(church_id: str, vendors: List[Vendor]) -> None:
    """Replace every vendor for a church. Atomic: delete-then-insert."""
    church_pk = _resolve_church_pk(church_id)
    with atomic_transaction() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM vendors WHERE church_id = %s", (church_pk,))
        for v in vendors:
            cur.execute(
                """
                INSERT INTO vendors (
                    church_id, name, ach_routing, ach_account_enc, ach_account_last4,
                    address, w9_on_file, notes, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    church_pk,
                    v.name,
                    v.ach_routing,
                    v.ach_account_enc,
                    v.ach_account_last4,
                    v.address,
                    bool(v.w9_on_file),
                    v.notes,
                ),
            )
        cur.close()
