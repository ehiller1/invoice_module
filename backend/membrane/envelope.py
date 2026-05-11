"""ImpactSignal envelope — frozen v1 (Phase 1).

The Pydantic model mirrors `schemas/impact_signal_v1.json`. Both are kept in
lockstep: any change requires a new envelope version (v2, ...). The
test suite cross-validates this model against the JSON Schema.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SCHEMA_PATH = Path(__file__).parent / "schemas" / "impact_signal_v1.json"
_SIGNAL_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_CHANNEL_RE = re.compile(r"^impact:[a-z_]+:[a-z0-9_]+$")


def load_schema() -> Dict[str, Any]:
    """Return the frozen v1 JSON Schema."""
    return json.loads(_SCHEMA_PATH.read_text())


class ImpactSignal(BaseModel):
    """Envelope for a signal crossing the membrane (v1, frozen)."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    envelope_version: Literal["1"] = "1"
    signal_id: int = Field(ge=1)
    signal_name: str
    event_id: str = Field(min_length=1)
    occurred_at: datetime
    privacy_class: Literal["P0", "P1"]
    crosses_membrane: bool
    target_channel: str
    payload: Dict[str, Any]
    source: str = Field(min_length=1)
    correlation_id: Optional[str] = None
    retention: Optional[str] = None

    @field_validator("signal_name")
    @classmethod
    def _validate_signal_name(cls, v: str) -> str:
        if not _SIGNAL_NAME_RE.match(v):
            raise ValueError(f"signal_name must be UPPER_SNAKE, got {v!r}")
        return v

    @field_validator("target_channel")
    @classmethod
    def _validate_channel(cls, v: str) -> str:
        if not _CHANNEL_RE.match(v):
            raise ValueError(f"target_channel must match {_CHANNEL_RE.pattern}, got {v!r}")
        return v


__all__ = ["ImpactSignal", "load_schema"]
