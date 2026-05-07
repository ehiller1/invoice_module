"""Vendor master persistence for FR-08 (payment initiation).

Vendors are stored per-church as JSON at backend/data/vendors_{church_id}.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from backend.models.schemas import Vendor


DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


def _vendor_path(church_id: str) -> Path:
    safe = "".join(c for c in church_id if c.isalnum() or c in "_-") or "default"
    return DATA_ROOT / f"vendors_{safe}.json"


def load_vendors(church_id: str) -> List[Vendor]:
    """Load all vendors for a church. Returns [] if file does not exist."""
    p = _vendor_path(church_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out: List[Vendor] = []
    for item in raw:
        try:
            out.append(Vendor(**item))
        except Exception:
            continue
    return out


def save_vendors(church_id: str, vendors: List[Vendor]) -> None:
    """Persist a list of vendors for a church (overwrites)."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    p = _vendor_path(church_id)
    payload = [v.model_dump(mode="json") for v in vendors]
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _normalize(s: str) -> str:
    """Lowercase + strip non-alphanumeric for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_vendor_by_name(church_id: str, name: str) -> Optional[Vendor]:
    """Fuzzy find vendor by name (case-insensitive substring/prefix match).

    Strategy:
      1. exact case-insensitive match
      2. normalized startswith / contains match
    """
    if not name:
        return None
    target = _normalize(name)
    if not target:
        return None
    vendors = load_vendors(church_id)
    # exact case-insensitive
    for v in vendors:
        if v.name.strip().lower() == name.strip().lower():
            return v
    # startswith / contains on normalized strings (both directions)
    for v in vendors:
        nv = _normalize(v.name)
        if not nv:
            continue
        if nv.startswith(target) or target.startswith(nv):
            return v
        if nv in target or target in nv:
            return v
    return None


def upsert_vendor(church_id: str, vendor: Vendor) -> Vendor:
    """Insert or update a vendor (matched by vendor_id)."""
    vendors = load_vendors(church_id)
    found = False
    out: List[Vendor] = []
    for v in vendors:
        if v.vendor_id == vendor.vendor_id:
            out.append(vendor)
            found = True
        else:
            out.append(v)
    if not found:
        out.append(vendor)
    save_vendors(church_id, out)
    return vendor
