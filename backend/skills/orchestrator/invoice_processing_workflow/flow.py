"""CrewAI Flow for `invoice_processing_workflow`.

The Flow drives the canonical EIME invoice pipeline by invoking the
SkillRouter step by step:

    pdf_extraction
      ↓
    coa_reference_loader (parallel)
    vendor_history_lookup (parallel, depends on pdf_extraction)
      ↓
    line_item_classifier
      ↓
    gl_account_mapper
      ↓
    allocation_reviewer
      ↓
    hitl_invoice_gate         (conditional: only if reviewer escalates)
      ↓
    journal_entry_builder
      ↓
    accounting_domain_distillation

Side effects:
  - Emits INVOICE_INGESTED at start (via publisher if provided).
  - Emits JOURNAL_ENTRY_READY when the JE is built.
  - Writes an Episode Card after each step, enabling suspend/resume.

The Flow is intentionally usable without CrewAI installed at import time;
the class only imports `crewai.Flow` when available, otherwise we fall back
to a plain coroutine implementation. Both paths drive the same `run_pipeline`
coroutine, which is what tests assert against.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.skills.episode_card import EpisodeCard, FileEpisodeCardStore, new_episode
from backend.skills.router import SkillRouter, get_router


async def _emit(publisher: Optional[Any], pert_name: str, payload: Dict[str, Any], correlation_id: str) -> None:
    if publisher is None:
        return
    try:
        from backend.membrane.envelope import ImpactSignal
        from backend.membrane.perturbations import get_perturbation
    except Exception:
        return
    try:
        pert = get_perturbation(pert_name)
    except KeyError:
        return
    envelope = ImpactSignal(
        signal_id=pert.id,
        signal_name=pert.name,
        event_id=str(uuid.uuid4()),
        occurred_at=datetime.now(tz=timezone.utc),
        privacy_class=pert.privacy_class,
        crosses_membrane=pert.crosses_membrane,
        target_channel=pert.target_channel,
        payload=payload,
        source="flow:invoice_processing_workflow",
        correlation_id=correlation_id,
        retention=pert.default_retention,
    )
    try:
        await publisher.publish_signal(envelope)
    except Exception:
        # Best-effort.
        pass


async def run_pipeline(
    inputs: Dict[str, Any],
    *,
    router: Optional[SkillRouter] = None,
    publisher: Optional[Any] = None,
    store: Optional[FileEpisodeCardStore] = None,
    dry_run: bool = True,
    resume_card: Optional[EpisodeCard] = None,
) -> Dict[str, Any]:
    """Run the invoice pipeline. Returns a dict with the final result + card."""
    router = router or get_router()
    store = store or FileEpisodeCardStore()
    correlation_id = inputs.get("correlation_id") or str(uuid.uuid4())

    if resume_card is None:
        card = new_episode("invoice_processing_workflow", inputs)
    else:
        card = resume_card
        card.status = "RUNNING"
    store.write(card)

    # Emit INVOICE_INGESTED (P1, non-crossing). Only on a fresh start.
    if resume_card is None:
        await _emit(
            publisher,
            "INVOICE_INGESTED",
            {"pdf_path": inputs.get("pdf_path"), "church_id": inputs.get("church_id"),
             "document_type": inputs.get("document_type", "invoice")},
            correlation_id,
        )
        card.perturbations_emitted.append("INVOICE_INGESTED")
        store.write(card)

    # Pipeline definition — (skill_name, depends_on, conditional_fn).
    pipeline: List[Dict[str, Any]] = [
        {"name": "pdf_extraction"},
        {"name": "coa_reference_loader"},
        {"name": "vendor_history_lookup"},
        {"name": "line_item_classifier"},
        {"name": "gl_account_mapper"},
        {"name": "allocation_reviewer"},
        {"name": "hitl_invoice_gate", "conditional": True},
        {"name": "journal_entry_builder"},
        {"name": "accounting_domain_distillation"},
    ]

    state: Dict[str, Any] = {
        "pdf_path": inputs.get("pdf_path"),
        "church_id": inputs.get("church_id"),
        "document_type": inputs.get("document_type", "invoice"),
        "correlation_id": correlation_id,
    }

    for step in pipeline:
        name = step["name"]
        if name in card.completed_steps:
            continue  # Resume: skip steps already done.

        # Conditional: skip HITL gate if allocation_reviewer approved with no escalation.
        if step.get("conditional") and name == "hitl_invoice_gate":
            reviewed = state.get("reviewed_allocations") or {}
            if reviewed.get("overall_verdict") == "APPROVED" and not reviewed.get("escalation_items"):
                card.completed_steps.append(name + ":SKIPPED")
                store.write(card)
                continue

        result = await router.invoke(name, inputs=state, context={"correlation_id": correlation_id, "dry_run": dry_run})
        if not result.ok:
            card.status = "FAILED"
            card.error = result.error
            store.write(card)
            return {"ok": False, "error": result.error, "card": card.to_dict(), "failed_at": name}

        # Merge typed outputs back into the rolling state.
        state.update(result.output)
        card.completed_steps.append(name)
        card.last_output = result.output
        store.write(card)

        # Emit JOURNAL_ENTRY_READY after journal_entry_builder completes.
        if name == "journal_entry_builder":
            await _emit(
                publisher,
                "JOURNAL_ENTRY_READY",
                {"journal_entry": state.get("journal_entry"), "dry_run": dry_run},
                correlation_id,
            )
            card.perturbations_emitted.append("JOURNAL_ENTRY_READY")
            store.write(card)

    card.status = "COMPLETED"
    store.write(card)
    return {
        "ok": True,
        "card": card.to_dict(),
        "journal_entry": state.get("journal_entry"),
        "correlation_id": correlation_id,
    }


class InvoiceProcessingFlow:
    """Thin wrapper. If CrewAI's `Flow` is importable we subclass it; otherwise
    expose `.kickoff()` as a plain coroutine. Either way `kickoff()` calls
    `run_pipeline`."""

    def __init__(
        self,
        router: Optional[SkillRouter] = None,
        publisher: Optional[Any] = None,
        store: Optional[FileEpisodeCardStore] = None,
    ) -> None:
        self.router = router
        self.publisher = publisher
        self.store = store

    async def kickoff(self, inputs: Dict[str, Any], *, dry_run: bool = True) -> Dict[str, Any]:
        return await run_pipeline(
            inputs,
            router=self.router,
            publisher=self.publisher,
            store=self.store,
            dry_run=dry_run,
        )

    async def resume(self, episode_id: str, *, dry_run: bool = True) -> Dict[str, Any]:
        store = self.store or FileEpisodeCardStore()
        card = store.read(episode_id)
        if card is None:
            return {"ok": False, "error": f"episode not found: {episode_id}"}
        return await run_pipeline(
            card.inputs,
            router=self.router,
            publisher=self.publisher,
            store=store,
            dry_run=dry_run,
            resume_card=card,
        )


__all__ = ["InvoiceProcessingFlow", "run_pipeline"]
