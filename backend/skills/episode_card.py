"""Episode Card — minimal suspend/resume state for Flow runs.

The Flow writes an Episode Card after each step so that a suspended pipeline
can resume from where it left off. The on-disk format is intentionally simple
JSON; a real backend (Postgres / Redis) can be swapped in later by replacing
`FileEpisodeCardStore` with an alternative store.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_DIR = Path(os.environ.get("EIME_EPISODE_DIR", "/tmp/eime_episodes"))


def _safe_copy(value: Any, _seen: Optional[set] = None, _depth: int = 0) -> Any:
    """JSON-safe deep copy that breaks cycles and caps depth."""
    if _depth > 12:
        return f"<truncated depth>{type(value).__name__}"
    if _seen is None:
        _seen = set()
    if isinstance(value, dict):
        oid = id(value)
        if oid in _seen:
            return "<cycle>"
        _seen.add(oid)
        return {str(k): _safe_copy(v, _seen, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        oid = id(value)
        if oid in _seen:
            return "<cycle>"
        _seen.add(oid)
        return [_safe_copy(v, _seen, _depth + 1) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class EpisodeCard:
    episode_id: str
    workflow: str
    status: str  # "RUNNING" | "SUSPENDED" | "COMPLETED" | "FAILED"
    started_at: str
    updated_at: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    completed_steps: List[str] = field(default_factory=list)
    last_output: Dict[str, Any] = field(default_factory=dict)
    perturbations_emitted: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "workflow": self.workflow,
            "status": self.status,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "inputs": dict(self.inputs),
            "completed_steps": list(self.completed_steps),
            "last_output": _safe_copy(self.last_output),
            "perturbations_emitted": list(self.perturbations_emitted),
            "error": self.error,
        }


class FileEpisodeCardStore:
    """JSON-on-disk Episode Card store (one file per episode)."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or DEFAULT_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, episode_id: str) -> Path:
        return self.root / f"{episode_id}.json"

    def write(self, card: EpisodeCard) -> None:
        card.updated_at = datetime.now(tz=timezone.utc).isoformat()
        self._path(card.episode_id).write_text(json.dumps(card.to_dict(), indent=2, default=str))

    def read(self, episode_id: str) -> Optional[EpisodeCard]:
        p = self._path(episode_id)
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        return EpisodeCard(**data)


def new_episode(workflow: str, inputs: Dict[str, Any]) -> EpisodeCard:
    import uuid as _uuid

    now = datetime.now(tz=timezone.utc).isoformat()
    return EpisodeCard(
        episode_id=str(_uuid.uuid4()),
        workflow=workflow,
        status="RUNNING",
        started_at=now,
        updated_at=now,
        inputs=dict(inputs),
    )


__all__ = ["EpisodeCard", "FileEpisodeCardStore", "new_episode", "DEFAULT_DIR"]
