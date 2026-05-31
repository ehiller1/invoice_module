"""EIME bundle — decision-matrix verdict policy stubs.

Wires context/decision_matrix.yaml verdict rules into a callable gate the
intent router (surface layer) and dispatchers consult before invoking an
agent/skill. Authority tiers map to backend/auth.py ROLE_LEVELS.

These are scaffolds for the dev team — the runtime binds them to the live
Context Pack assembled by the memory_fabric_context_pack skill.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
MATRIX = yaml.safe_load(open(BUNDLE_ROOT / "context" / "decision_matrix.yaml"))

ROLE_RANK = {t["tier"]: t["rank"] for t in MATRIX["authority_tiers"]}


def _rank(role: Optional[str]) -> int:
    return ROLE_RANK.get((role or "").upper(), 0)


def has_tier(role: Optional[str], required: str) -> bool:
    """True when `role` is at or above `required` (per ROLE_LEVELS ordering)."""
    return _rank(role) >= _rank(required)


def verdict(request: Dict[str, Any], context_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Return {verdict, side_effect?, rationale} for a request given context.

    Verdicts: allow | deny | escalate | flag | redact_amounts.
    """
    constraints = context_snapshot.get("constraints", {})
    blocking = constraints.get("blocking_rules", [])
    user_role = context_snapshot.get("facts", {}).get("user", {}).get("role")
    action = request.get("action")

    # Hard blocks first.
    if "restricted_fund_violation" in blocking:
        return {"verdict": "deny", "side_effect": "FUND_RESTRICTION_VIOLATION",
                "rationale": "Restricted-fund violation — hard block."}
    if request.get("is_probable_duplicate"):
        return {"verdict": "deny", "side_effect": "PAYMENT_DEDUP_RISK",
                "rationale": "Duplicate payment — hard block."}

    # Posting authority.
    if action == "post_je" and not has_tier(user_role, "TREASURER_ADMIN"):
        return {"verdict": "escalate", "side_effect": "HITL_ESCALATION",
                "rationale": "Only TREASURER_ADMIN may post; escalating."}

    # Approval staging.
    if action == "approve":
        stage = request.get("stage", "stage_1")
        needed = "TREASURER_ADMIN" if stage == "final" else "BUDGET_OWNER"
        if not has_tier(user_role, needed):
            return {"verdict": "escalate", "side_effect": "HITL_ESCALATION",
                    "rationale": f"Approval stage {stage} requires {needed}."}

    # Amount disclosure.
    if request.get("reads_je_amounts") and not has_tier(user_role, "FINANCE_STAFF"):
        return {"verdict": "redact_amounts",
                "rationale": "JE amounts visible to FINANCE_STAFF+ only."}

    # Soft flags.
    if request.get("breaches_budget"):
        return {"verdict": "flag", "side_effect": "BUDGET_OVERAGE_RISK",
                "rationale": "Budget threshold breached."}
    if request.get("policy_gate_fired"):
        return {"verdict": "flag", "side_effect": "POLICY_VIOLATION",
                "rationale": "Policy gate fired."}

    return {"verdict": "allow", "rationale": "No gate triggered."}
