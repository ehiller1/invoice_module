"""Orchestrator archetype dispatcher.

Orchestrators return ExecutionPlans. For `invoice_processing_workflow` the
plan is the canonical EIME pipeline. The CrewAI Flow consumes this plan to
drive the pipeline.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import ArchetypeDispatcher

CANONICAL_PIPELINE: List[Dict[str, Any]] = [
    {"archetype": "worker",          "skill_name": "pdf_extraction",        "depends_on": []},
    {"archetype": "researcher",      "skill_name": "coa_reference_loader",  "depends_on": []},
    {"archetype": "researcher",      "skill_name": "vendor_history_lookup", "depends_on": ["pdf_extraction"]},
    {"archetype": "worker",          "skill_name": "line_item_classifier",  "depends_on": ["pdf_extraction", "coa_reference_loader"]},
    {"archetype": "worker",          "skill_name": "gl_account_mapper",     "depends_on": ["line_item_classifier"]},
    {"archetype": "reviewer",        "skill_name": "allocation_reviewer",   "depends_on": ["gl_account_mapper"]},
    {"archetype": "conversationalist","skill_name": "hitl_invoice_gate",    "depends_on": ["allocation_reviewer"], "conditional": True},
    {"archetype": "worker",          "skill_name": "journal_entry_builder", "depends_on": ["allocation_reviewer"]},
    {"archetype": "membrane",        "skill_name": "accounting_domain_distillation", "depends_on": ["journal_entry_builder"]},
]


class OrchestratorDispatcher(ArchetypeDispatcher):
    archetype = "orchestrator"

    async def _stub_output(
        self,
        skill_name: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        base = await super()._stub_output(skill_name, inputs, context, record)
        if skill_name == "invoice_processing_workflow":
            base["execution_plan"] = [dict(step) for step in CANONICAL_PIPELINE]
        return base


__all__ = ["OrchestratorDispatcher", "CANONICAL_PIPELINE"]
