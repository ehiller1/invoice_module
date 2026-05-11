"""Worker archetype dispatcher.

Workers perform a single deterministic transformation: extract, classify, map,
build. Most workers ship a SKILL.md only; the dispatcher returns a typed stub
unless the skill directory provides an `entry.py` with a `run(inputs, context)`
function.
"""
from __future__ import annotations

from typing import Any, Dict

from .base import ArchetypeDispatcher


class WorkerDispatcher(ArchetypeDispatcher):
    archetype = "worker"
    accepted_archetypes = ("membrane",)  # membrane skills are single-transform workers

    async def _stub_output(
        self,
        skill_name: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        base = await super()._stub_output(skill_name, inputs, context, record)
        # Domain-shaped stubs for the canonical pipeline so the Flow can chain.
        if skill_name == "pdf_extraction":
            base["invoice_document"] = {
                "vendor_name": "STUB_VENDOR",
                "invoice_number": "STUB-001",
                "total_amount": 0.0,
                "line_items": [],
                "warnings": [],
                "requires_manual_review": False,
            }
        elif skill_name == "line_item_classifier":
            base["classified_line_items"] = []
        elif skill_name == "gl_account_mapper":
            base["draft_allocations"] = {
                "postings": [],
                "total_debits": 0.0,
                "total_credits": 0.0,
                "balanced": True,
            }
        elif skill_name == "journal_entry_builder":
            base["journal_entry"] = {
                "entry_id": "JE-STUB-001",
                "lines": [],
                "total_debits": 0.0,
                "total_credits": 0.0,
                "balanced": True,
                "status": "DRAFT",
            }
        return base


__all__ = ["WorkerDispatcher"]
