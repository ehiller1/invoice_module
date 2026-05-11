"""Base ArchetypeDispatcher + DispatchResult."""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class DispatchResult:
    """Structured result returned from any skill invocation."""

    skill_name: str
    archetype: str
    ok: bool
    output: Dict[str, Any] = field(default_factory=dict)
    perturbations_emitted: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "archetype": self.archetype,
            "ok": self.ok,
            "output": self.output,
            "perturbations_emitted": list(self.perturbations_emitted),
            "error": self.error,
        }


class ArchetypeDispatcher:
    """Common machinery: load optional entry.py from the skill directory."""

    archetype: str = "base"
    accepted_archetypes: tuple = ()  # extra archetypes this dispatcher will handle

    def __init__(self, registry: Optional[Any] = None) -> None:
        from backend.tools.skill_registry import get_registry

        self.registry = registry or get_registry()

    # ------------------------------------------------------------------ utils
    def _load_entry_module(self, skill_record: Dict[str, Any]):
        """Try to import `entry.py` from the skill's directory. Returns module or None."""
        skill_dir = Path(skill_record["path"]).parent
        entry_path = skill_dir / "entry.py"
        if not entry_path.exists():
            return None
        # Build a unique module name to avoid collisions across skills with the same filename.
        mod_name = f"backend_skill_entry__{skill_record['name']}"
        spec = importlib.util.spec_from_file_location(mod_name, entry_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    def _meta_perturbations(self, skill_record: Dict[str, Any]) -> List[str]:
        # The registry strips underscore-prefixed fields but keeps the public ones,
        # however perturbations_emitted is *not* in the registry index — reload via frontmatter.
        try:
            import frontmatter

            post = frontmatter.load(skill_record["path"])
            val = post.metadata.get("perturbations_emitted") or []
            if isinstance(val, list):
                return [str(x) for x in val]
        except Exception:
            pass
        return []

    # ----------------------------------------------------------------- invoke
    async def invoke(
        self,
        skill_name: str,
        inputs: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> DispatchResult:
        context = context or {}
        record = self.registry.get(skill_name)
        if not record:
            return DispatchResult(
                skill_name=skill_name,
                archetype=self.archetype,
                ok=False,
                error=f"skill not found: {skill_name}",
            )
        allowed = {self.archetype, *self.accepted_archetypes}
        if record["archetype"] not in allowed:
            return DispatchResult(
                skill_name=skill_name,
                archetype=self.archetype,
                ok=False,
                error=(
                    f"archetype mismatch: skill {skill_name!r} is {record['archetype']}, "
                    f"dispatcher is {self.archetype}"
                ),
            )
        try:
            module = self._load_entry_module(record)
            if module is not None and hasattr(module, "run"):
                run = getattr(module, "run")
                # Support both sync and async entry points.
                if hasattr(run, "__await__"):
                    output = await run(inputs, context)  # type: ignore[misc]
                else:
                    result = run(inputs, context)
                    if hasattr(result, "__await__"):
                        output = await result  # type: ignore[assignment]
                    else:
                        output = result
            else:
                output = await self._stub_output(skill_name, inputs, context, record)
        except Exception as exc:  # pragma: no cover - exercised in tests via failure injection
            return DispatchResult(
                skill_name=skill_name,
                archetype=self.archetype,
                ok=False,
                output={},
                perturbations_emitted=[],
                error=f"{type(exc).__name__}: {exc}",
            )
        if not isinstance(output, dict):
            output = {"value": output}
        return DispatchResult(
            skill_name=skill_name,
            archetype=self.archetype,
            ok=True,
            output=output,
            perturbations_emitted=self._meta_perturbations(record),
        )

    async def _stub_output(
        self,
        skill_name: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Default stub: echo inputs + describe expected output. Overridable per archetype."""
        return {
            "skill_name": skill_name,
            "archetype": self.archetype,
            "expected_output": record.get("expected_output", ""),
            "echo_inputs": inputs,
            "stub": True,
        }


__all__ = ["ArchetypeDispatcher", "DispatchResult"]
