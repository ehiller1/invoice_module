"""FR-NF: Per-agent LLM model routing.

Stores admin-configured overrides in `backend/data/model_config.json`.
Agents call `resolve_model(agent_name)` to get the active model id.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "model_config.json"


# Default model assignments per agent.
DEFAULTS: Dict[str, str] = {
    "gl_classifier": "claude-sonnet-4-5-20250929",
    "fund_router": "claude-sonnet-4-5-20250929",
    "reviewer": "claude-sonnet-4-5-20250929",
    "treasurer_chat": "claude-sonnet-4-5-20250929",
    "fraud_detector": "claude-sonnet-4-5-20250929",
    "knowledge_base": "claude-sonnet-4-5-20250929",
}


def load_model_config() -> Dict[str, str]:
    """Load the merged config (defaults + overrides)."""
    overrides: Dict[str, str] = {}
    if _CONFIG_PATH.exists():
        try:
            overrides = json.loads(_CONFIG_PATH.read_text() or "{}")
        except Exception:
            overrides = {}
    return {**DEFAULTS, **{k: v for k, v in overrides.items() if isinstance(v, str)}}


def save_model_config(overrides: Dict[str, Any]) -> Dict[str, str]:
    """Persist override config and return the merged result."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {k: str(v) for k, v in overrides.items() if isinstance(v, str)}
    _CONFIG_PATH.write_text(json.dumps(cleaned, indent=2))
    return load_model_config()


def resolve_model(agent_name: str) -> str:
    """Return the active model id for an agent. Falls back to DEFAULTS, then
    the global ANTHROPIC_MODEL env var, then a hard default."""
    cfg = load_model_config()
    if agent_name in cfg:
        return cfg[agent_name]
    if agent_name in DEFAULTS:
        return DEFAULTS[agent_name]
    return os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
