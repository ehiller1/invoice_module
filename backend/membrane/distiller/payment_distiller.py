"""PaymentDistiller — distills payment-pipeline signals (PAYMENT_DEDUP_RISK)."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .base import Distiller


_WHITELIST = ("payment_id", "prior_payment_id", "hard_block", "job_id")


class PaymentDistiller(Distiller):
    def distill(self, raw_event: Any, context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        payload: Mapping[str, Any] = getattr(raw_event, "payload", {}) or {}
        out: Dict[str, Any] = {k: payload.get(k) for k in _WHITELIST if k in payload}
        out["signal_name"] = getattr(raw_event, "signal_name", None)
        return out


__all__ = ["PaymentDistiller"]
