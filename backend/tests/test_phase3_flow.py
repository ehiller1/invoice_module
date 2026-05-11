"""Phase 3: InvoiceProcessingFlow end-to-end (dry run, no posting)."""
from __future__ import annotations

import pytest

from backend.membrane.transport import LocalTransport
from backend.membrane.transport.publisher import Publisher
from backend.skills.episode_card import FileEpisodeCardStore
from backend.skills.orchestrator.invoice_processing_workflow import (
    InvoiceProcessingFlow,
    run_pipeline,
)
from backend.skills.router import SkillRouter
from backend.tools.skill_registry import SkillRegistry


@pytest.fixture
def store(tmp_path) -> FileEpisodeCardStore:
    return FileEpisodeCardStore(root=tmp_path / "episodes")


@pytest.fixture
def router() -> SkillRouter:
    return SkillRouter(registry=SkillRegistry())


@pytest.mark.asyncio
async def test_flow_runs_end_to_end(router, store) -> None:
    transport = LocalTransport()
    publisher = Publisher(transport)
    flow = InvoiceProcessingFlow(router=router, publisher=publisher, store=store)
    result = await flow.kickoff(
        {"pdf_path": "/tmp/x.pdf", "church_id": "C1", "document_type": "invoice"}, dry_run=True
    )
    assert result["ok"], result
    card = result["card"]
    assert card["status"] == "COMPLETED"
    # All canonical non-conditional steps completed in order.
    for required in ("pdf_extraction", "coa_reference_loader", "line_item_classifier",
                     "gl_account_mapper", "allocation_reviewer", "journal_entry_builder",
                     "accounting_domain_distillation"):
        assert required in card["completed_steps"], f"missing step {required}"


@pytest.mark.asyncio
async def test_flow_emits_invoice_ingested_and_journal_entry_ready(router, store) -> None:
    transport = LocalTransport()
    publisher = Publisher(transport)
    flow = InvoiceProcessingFlow(router=router, publisher=publisher, store=store)
    result = await flow.kickoff(
        {"pdf_path": "/tmp/x.pdf", "church_id": "C1"}, dry_run=True
    )
    perts = result["card"]["perturbations_emitted"]
    assert "INVOICE_INGESTED" in perts
    assert "JOURNAL_ENTRY_READY" in perts


@pytest.mark.asyncio
async def test_flow_writes_episode_card_each_step(router, store) -> None:
    flow = InvoiceProcessingFlow(router=router, publisher=None, store=store)
    result = await flow.kickoff({"pdf_path": "/tmp/x.pdf", "church_id": "C1"})
    eid = result["card"]["episode_id"]
    reloaded = store.read(eid)
    assert reloaded is not None
    assert reloaded.status == "COMPLETED"
    assert len(reloaded.completed_steps) >= 7


@pytest.mark.asyncio
async def test_flow_skips_hitl_when_no_escalation(router, store) -> None:
    """Default reviewer stub returns APPROVED with no escalations, so HITL is skipped."""
    flow = InvoiceProcessingFlow(router=router, publisher=None, store=store)
    result = await flow.kickoff({"pdf_path": "/tmp/x.pdf", "church_id": "C1"})
    steps = result["card"]["completed_steps"]
    assert "hitl_invoice_gate:SKIPPED" in steps
    assert "hitl_invoice_gate" not in steps


@pytest.mark.asyncio
async def test_flow_resume_from_suspended_card(router, tmp_path) -> None:
    store = FileEpisodeCardStore(root=tmp_path / "ep")
    flow = InvoiceProcessingFlow(router=router, publisher=None, store=store)
    # First, run once to completion to get a real card on disk.
    result = await flow.kickoff({"pdf_path": "/tmp/x.pdf", "church_id": "C1"})
    eid = result["card"]["episode_id"]
    # Resume should be a no-op (all steps already in completed_steps).
    resumed = await flow.resume(eid)
    assert resumed["ok"]
    assert resumed["card"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_flow_dry_run_does_not_post(router, store) -> None:
    """Dry run must not call any posting tool; the JE entry should still be built."""
    result = await run_pipeline(
        {"pdf_path": "/tmp/x.pdf", "church_id": "C1"},
        router=router, publisher=None, store=store, dry_run=True,
    )
    assert result["ok"]
    je = result["journal_entry"]
    assert je is not None
    assert je["status"] == "DRAFT"  # never POSTED in dry-run
