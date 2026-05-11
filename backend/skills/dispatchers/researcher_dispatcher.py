"""Researcher archetype dispatcher.

Researchers load contextual reference data (CoA, vendor history, denomination
rules). They are read-only.
"""
from __future__ import annotations

from typing import Any, Dict

from .base import ArchetypeDispatcher


class ResearcherDispatcher(ArchetypeDispatcher):
    archetype = "researcher"

    async def _stub_output(
        self,
        skill_name: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        base = await super()._stub_output(skill_name, inputs, context, record)
        if skill_name == "coa_reference_loader":
            base["accounting_context"] = {
                "accounts": [],
                "funds": [],
                "allocation_schedules": [],
                "capitalisation_threshold_usd": 5000,
            }
        elif skill_name == "vendor_history_lookup":
            base["vendor_history"] = []
        return base


__all__ = ["ResearcherDispatcher"]
