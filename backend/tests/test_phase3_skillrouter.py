"""Phase 3: SkillRouter + archetype dispatch tests."""
from __future__ import annotations

import pytest

from backend.skills.router import SkillRouter
from backend.tools.skill_registry import SkillRegistry


@pytest.fixture
def router() -> SkillRouter:
    return SkillRouter(registry=SkillRegistry())


@pytest.mark.asyncio
async def test_worker_dispatch_returns_invoice_document(router: SkillRouter) -> None:
    result = await router.invoke("pdf_extraction", {"pdf_path": "/tmp/x.pdf", "document_type": "invoice"})
    assert result.ok
    assert result.archetype == "worker"
    assert "invoice_document" in result.output


@pytest.mark.asyncio
async def test_researcher_dispatch_loads_context(router: SkillRouter) -> None:
    result = await router.invoke("coa_reference_loader", {"church_id": "C1", "fiscal_year": 2026})
    assert result.ok
    assert result.archetype == "researcher"
    assert "accounting_context" in result.output


@pytest.mark.asyncio
async def test_reviewer_dispatch_returns_verdict(router: SkillRouter) -> None:
    result = await router.invoke("allocation_reviewer", {"draft_allocations": {}, "accounting_context": {}})
    assert result.ok
    assert result.output["reviewed_allocations"]["overall_verdict"] == "APPROVED"


@pytest.mark.asyncio
async def test_conversationalist_dispatch_returns_decisions(router: SkillRouter) -> None:
    result = await router.invoke("hitl_invoice_gate", {"escalation_items": []})
    assert result.ok
    assert result.output["hitl_decisions"]["all_resolved"] is True


@pytest.mark.asyncio
async def test_orchestrator_returns_execution_plan(router: SkillRouter) -> None:
    result = await router.invoke("invoice_processing_workflow", {"pdf_path": "/tmp/x.pdf", "church_id": "C1"})
    assert result.ok
    plan = result.output["execution_plan"]
    assert any(s["skill_name"] == "pdf_extraction" for s in plan)
    assert any(s["skill_name"] == "journal_entry_builder" for s in plan)


@pytest.mark.asyncio
async def test_unknown_skill_returns_error(router: SkillRouter) -> None:
    result = await router.invoke("does_not_exist", {})
    assert not result.ok
    assert "not found" in (result.error or "")


@pytest.mark.asyncio
async def test_mvp_agent_skills_present(router: SkillRouter) -> None:
    """All 5 MVP agents should be discoverable as orchestrator skills."""
    names = {s["name"] for s in router.list_skills()}
    for n in ("drafting_agent", "reconciliation_agent", "compliance_agent",
              "auto_post_agent", "advisor_agent"):
        assert n in names, f"missing MVP agent skill: {n}"


@pytest.mark.asyncio
async def test_mvp_agent_invocation_via_entry_py(router: SkillRouter) -> None:
    """The drafting_agent skill ships with entry.py that returns ok=True."""
    result = await router.invoke("drafting_agent", {"description": "Pay vendor X $100", "church_id": "C1"})
    assert result.ok
    assert result.output.get("agent") == "drafting_agent"


@pytest.mark.asyncio
async def test_router_registered_mvp_agent_overrides_entry(router: SkillRouter) -> None:
    """A programmatically registered MVP callable wins over entry.py."""
    async def fake_agent(inputs, ctx):
        return {"ok": True, "agent": "drafting_agent", "stamped": "fake"}
    router.register_mvp_agent("drafting_agent", fake_agent)
    r = await router.invoke("drafting_agent", {"description": "x"})
    assert r.ok
    assert r.output["stamped"] == "fake"
