"""Skill router/registry. Discovers SKILL.md files at runtime per FRS §3.1."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import frontmatter


SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"


class SkillRegistry:
    """Registry that scans SKILL.md frontmatter (cheap) and lazy-loads bodies."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or SKILLS_ROOT
        self._index: Dict[str, Dict] = {}
        self._scan()

    def _scan(self) -> None:
        self._index.clear()
        for skill_md in self.root.rglob("SKILL.md"):
            try:
                post = frontmatter.load(skill_md)
            except Exception:
                continue
            meta = post.metadata
            name = meta.get("skill_name")
            if not name:
                continue
            self._index[name] = {
                "name": name,
                "archetype": meta.get("archetype", "worker"),
                "description": meta.get("description", ""),
                "inputs": meta.get("inputs", []),
                "expected_output": meta.get("expected_output", ""),
                "allowed_tools": meta.get("allowed_tools", []),
                "path": str(skill_md),
                "_body_cache": None,
            }

    def search(self, archetype: Optional[str] = None) -> List[Dict]:
        rows = list(self._index.values())
        if archetype:
            rows = [r for r in rows if r["archetype"] == archetype]
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

    def get(self, skill_name: str) -> Optional[Dict]:
        record = self._index.get(skill_name)
        if not record:
            return None
        return {k: v for k, v in record.items() if not k.startswith("_")}

    def load_body(self, skill_name: str) -> str:
        record = self._index.get(skill_name)
        if not record:
            raise KeyError(skill_name)
        if record["_body_cache"] is None:
            post = frontmatter.load(record["path"])
            record["_body_cache"] = post.content
        return record["_body_cache"]

    def reload(self) -> None:
        self._scan()


_registry: Optional[SkillRegistry] = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
