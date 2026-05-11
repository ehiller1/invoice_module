"""Redactor — privacy-class enforcement at the membrane (Phase 7).

Each field in a payload is associated with a privacy class. Fields are
redacted from the output payload when the calling principal's RBAC role
does not satisfy the field's minimum class.

Privacy classes:
  P0 — public/operational: visible to all roles (including unauthenticated)
  P1 — internal operational: FINANCE_STAFF and above
  P2 — financial detail: BUDGET_OWNER and above
  P3 — PII / sensitive: TREASURER and above (or ADMIN)

When `strict=True`, attempting to redact any P3 field raises
PrivacyViolationError rather than silently masking it.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Mapping, Tuple


class PrivacyClass(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class Role(str, Enum):
    PUBLIC = "PUBLIC"
    FINANCE_STAFF = "FINANCE_STAFF"
    BUDGET_OWNER = "BUDGET_OWNER"
    TREASURER = "TREASURER"
    ADMIN = "ADMIN"


# Role rank: higher = more access.
_ROLE_RANK: Dict[Role, int] = {
    Role.PUBLIC: 0,
    Role.FINANCE_STAFF: 1,
    Role.BUDGET_OWNER: 2,
    Role.TREASURER: 3,
    Role.ADMIN: 4,
}

# Minimum role required to view a privacy class.
_MIN_ROLE: Dict[PrivacyClass, int] = {
    PrivacyClass.P0: 0,  # all
    PrivacyClass.P1: 1,  # FINANCE_STAFF+
    PrivacyClass.P2: 2,  # BUDGET_OWNER+
    PrivacyClass.P3: 3,  # TREASURER+ (ADMIN also has rank 4)
}

_DEFAULT_CLASS = PrivacyClass.P1


class PrivacyViolationError(Exception):
    """Raised in strict mode when a P3 field cannot be shown to the caller."""


class Redactor:
    def __init__(self, strict: bool = False, mask: str = "[REDACTED]") -> None:
        self.strict = strict
        self.mask = mask

    def _coerce_class(self, value: Any) -> PrivacyClass:
        try:
            return PrivacyClass(value)
        except ValueError as exc:
            raise ValueError(f"Invalid privacy class: {value!r}") from exc

    def _role_rank(self, role: Role) -> int:
        return _ROLE_RANK.get(role, -1)

    def redact(
        self,
        payload: Mapping[str, Any],
        field_classes: Mapping[str, str],
        *,
        role: Role,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Return (redacted_payload, audit_entry).

        - Fields not declared in `field_classes` default to P1.
        - Fields whose class is above the caller's role are removed.
        - In strict mode, redacting a P3 field raises PrivacyViolationError.
        """
        # Validate declared classes up-front.
        for k, v in field_classes.items():
            self._coerce_class(v)

        caller_rank = self._role_rank(role)
        out: Dict[str, Any] = {}
        redacted: List[str] = []

        for k, v in payload.items():
            cls = self._coerce_class(field_classes[k]) if k in field_classes else _DEFAULT_CLASS
            min_rank = _MIN_ROLE[cls]
            if caller_rank >= min_rank:
                out[k] = v
            else:
                if cls == PrivacyClass.P3 and self.strict:
                    raise PrivacyViolationError(
                        f"P3 field {k!r} cannot be shown to role {role.value}"
                    )
                redacted.append(k)

        audit = {
            "role": role.value,
            "redacted_fields": redacted,
            "total_fields": len(payload),
        }
        return out, audit


__all__ = [
    "PrivacyClass",
    "PrivacyViolationError",
    "Redactor",
    "Role",
]
