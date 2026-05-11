"""PolicyDistiller — POLICY_VIOLATION and FUND_RESTRICTION_VIOLATION."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .base import Distiller


_WHITELISTS = {
    "POLICY_VIOLATION":           ("policy_id", "rule_violated", "entity_affected", "job_id"),
    "FUND_RESTRICTION_VIOLATION": ("fund", "restriction_type", "violation_detail", "hard_block", "job_id"),
}


class PolicyDistiller(Distiller):
    def distill(self, raw_event: Any, context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        name = getattr(raw_event, "signal_name", None)
        payload: Mapping[str, Any] = getattr(raw_event, "payload", {}) or {}
        whitelist = _WHITELISTS.get(name or "", ())
        out: Dict[str, Any] = {k: payload.get(k) for k in whitelist if k in payload}
        out["signal_name"] = name
        return out


__all__ = ["PolicyDistiller"]
