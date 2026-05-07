"""JE state machine with role-based transition gates (FR-06.4)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Set

from backend.models.schemas import JEStatus


# Allowed role per transition target
ROLE_GATES: Dict[JEStatus, Set[str]] = {
    JEStatus.OPEN: {"FINANCE_STAFF", "BUDGET_OWNER", "TREASURER_ADMIN"},
    JEStatus.PENDING_TREASURER: {"BUDGET_OWNER", "TREASURER_ADMIN"},
    JEStatus.APPROVED: {"TREASURER_ADMIN"},
    JEStatus.POSTED: {"TREASURER_ADMIN"},
    JEStatus.POSTING_FAILED: {"TREASURER_ADMIN", "SYSTEM"},
    JEStatus.REJECTED: {"BUDGET_OWNER", "TREASURER_ADMIN"},
}

# Allowed transitions: from -> {to}
TRANSITIONS: Dict[JEStatus, Set[JEStatus]] = {
    JEStatus.DRAFT: {JEStatus.OPEN, JEStatus.REJECTED},
    JEStatus.OPEN: {JEStatus.PENDING_TREASURER, JEStatus.REJECTED},
    JEStatus.PENDING_TREASURER: {JEStatus.APPROVED, JEStatus.REJECTED},
    JEStatus.APPROVED: {JEStatus.POSTED, JEStatus.POSTING_FAILED},
    JEStatus.POSTING_FAILED: {JEStatus.APPROVED, JEStatus.POSTED},  # retry
    JEStatus.POSTED: set(),                                          # terminal
    JEStatus.REJECTED: set(),                                        # terminal
}


class JEStateError(Exception):
    """Raised when an illegal JE transition is attempted."""


def _coerce(state: Any) -> JEStatus:
    if isinstance(state, JEStatus):
        return state
    return JEStatus(state)


def can_transition(from_state: Any, to_state: Any, role: str) -> bool:
    """Return True iff the transition is legal for the supplied role."""
    try:
        f = _coerce(from_state)
        t = _coerce(to_state)
    except Exception:
        return False
    if t not in TRANSITIONS.get(f, set()):
        return False
    if role not in ROLE_GATES.get(t, set()):
        return False
    return True


def transition(je: Any, to_state: Any, role: str,
               actor_email: str, notes: str = "") -> Any:
    """Mutate `je` in-place: update status & append an audit_trail entry.

    `je` may be a Pydantic model or a plain dict-like object. The function
    supports both attribute and item access patterns and tolerates a missing
    `audit_trail` attribute (common on the existing JournalEntry model).
    """
    f = _coerce(_get(je, "status"))
    t = _coerce(to_state)
    if not can_transition(f, t, role):
        raise JEStateError(
            f"Cannot transition {f.value} -> {t.value} as role {role}"
        )
    _set(je, "status", t)
    trail = list(_get(je, "audit_trail", default=None) or [])
    trail.append({
        "from": f.value,
        "to": t.value,
        "role": role,
        "actor": actor_email,
        "notes": notes,
        "timestamp": datetime.utcnow().isoformat(),
    })
    _set(je, "audit_trail", trail)
    return je


# ---------- attribute / item dual-access helpers ----------

_SENTINEL = object()


def _get(obj: Any, name: str, default: Any = _SENTINEL) -> Any:
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict) and name in obj:
        return obj[name]
    if default is _SENTINEL:
        raise AttributeError(name)
    return default


def _set(obj: Any, name: str, value: Any) -> None:
    # Pydantic models accept attribute set if field exists or model_config allows extras.
    try:
        setattr(obj, name, value)
        return
    except Exception:
        pass
    if isinstance(obj, dict):
        obj[name] = value
        return
    # Fallback — use object.__setattr__ to bypass restrictive __setattr__
    object.__setattr__(obj, name, value)
