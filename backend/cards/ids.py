"""Validation for user-supplied identifiers used in card IDs.

Card IDs are stored as plain strings but are also used as filesystem-adjacent
keys (audit lookups, prefix queries, debug logs). Free-form input would let a
caller collide reserved suffixes (e.g. "-closed"), inject path separators, or
produce ambiguous prefix matches.
"""
from __future__ import annotations

import re

# Allowed: alnum, underscore, hyphen, dot. Max 128 chars. Cannot start with hyphen.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.\-]{0,127}$")

# Suffixes reserved by card-writing functions; user IDs must not end with these
# to avoid collisions with derived card IDs (e.g. f"audit-{id}-closed").
_RESERVED_SUFFIXES = ("-closed", "-resolved", "-deleted", "-archived")


def validate_id_component(value: str, *, field: str = "id") -> str:
    """Validate a user-supplied ID component and return it unchanged.

    Raises:
        ValueError: If the value contains disallowed characters, is empty,
            exceeds 128 chars, or collides with a reserved suffix.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {type(value).__name__}")
    if not _ID_PATTERN.match(value):
        raise ValueError(
            f"{field} must match [A-Za-z0-9_.-]{{1,128}} and not start with '-', got {value!r}"
        )
    for suffix in _RESERVED_SUFFIXES:
        if value.endswith(suffix):
            raise ValueError(f"{field} {value!r} ends with reserved suffix {suffix!r}")
    return value


__all__ = ["validate_id_component"]
