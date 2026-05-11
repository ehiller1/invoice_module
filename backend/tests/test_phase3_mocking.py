"""Phase 3: mock skill outcomes (success/failure/retry/escalation)."""
from __future__ import annotations

import pytest

from backend.skills.dispatchers.base import DispatchResult
from backend.skills.orchestrator.invoice_processing_workflow import run_pipeline
from backend.skills.router import SkillRouter
from backend.tools.skill_registry import SkillRegistry


class _FakeRouter:
    """Stand-in router whose `invoke()` returns scripted DispatchResults."""

    def __init__(self, script):
        self._script = dict(script)
        self.calls = []

    async def invoke(self, skill_name, inputs=None, context=None):
        self.calls.append(skill_name)
        if skill_name in self._script:
            return self._script[skill_name]
        return DispatchResult(skill_name=skill_name, archetype="worker", ok=True, output={})


@pytest.mark.asyncio
async def test_pipeline_halts_on_step_failure(tmp_path) -> None:
    from backend.skills.episode_card import FileEpisodeCardStore

    fake = _FakeRouter({
        "gl_account_mapper": DispatchResult(
            skill_name="gl_account_mapper", archetype="worker", ok=False,
            error="account resolution failed",
        ),
    })
    result = await run_pipeline(
        {"pdf_path": "/tmp/x.pdf", "church_id": "C1"},
        router=fake, store=FileEpisodeCardStore(root=tmp_path / "ep"), dry_run=True,
    )
    assert not result["ok"]
    assert result["failed_at"] == "gl_account_mapper"
    assert "account resolution" in result["error"]


@pytest.mark.asyncio
async def test_pipeline_runs_hitl_when_reviewer_escalates(tmp_path) -> None:
    from backend.skills.episode_card import FileEpisodeCardStore

    fake = _FakeRouter({
        "allocation_reviewer": DispatchResult(
            skill_name="allocation_reviewer", archetype="reviewer", ok=True,
            output={"reviewed_allocations": {
                "overall_verdict": "NEEDS_HITL",
                "escalation_items": [{"line_id": 1, "reason": "ambiguous"}],
            }},
        ),
        "hitl_invoice_gate": DispatchResult(
            skill_name="hitl_invoice_gate", archetype="conversationalist", ok=True,
            output={"hitl_decisions": {"line_decisions": [{"line_id": 1, "approved": True}],
                                         "all_resolved": True}},
        ),
    })
    result = await run_pipeline(
        {"pdf_path": "/tmp/x.pdf", "church_id": "C1"},
        router=fake, store=FileEpisodeCardStore(root=tmp_path / "ep"), dry_run=True,
    )
    assert result["ok"]
    assert "hitl_invoice_gate" in fake.calls
    assert "hitl_invoice_gate" in result["card"]["completed_steps"]


@pytest.mark.asyncio
async def test_router_retry_pattern_via_registered_callable() -> None:
    """A flaky MVP-agent callable: first call fails, second succeeds — the router
    does NOT auto-retry, but a wrapper closure can implement retry and still surface
    a single ok result. This documents the contract: retries are caller-owned."""
    attempts = {"n": 0}

    async def flaky(inputs, ctx):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")
        return {"ok": True, "tries": attempts["n"]}

    router = SkillRouter(registry=SkillRegistry())
    router.register_mvp_agent("drafting_agent", flaky)

    first = await router.invoke("drafting_agent", {})
    assert not first.ok
    assert "transient" in (first.error or "")

    second = await router.invoke("drafting_agent", {})
    assert second.ok
    assert second.output["tries"] == 2


@pytest.mark.asyncio
async def test_perturbation_emission_via_router(monkeypatch) -> None:
    """When a publisher is provided, skills that declare perturbations_emitted
    actually publish ImpactSignal envelopes."""
    from backend.membrane.transport import LocalTransport
    from backend.membrane.transport.publisher import Publisher

    transport = LocalTransport()
    publisher = Publisher(transport)
    router = SkillRouter(registry=SkillRegistry(), publisher=publisher)

    # journal_entry_builder declares JOURNAL_ENTRY_READY.
    result = await router.invoke(
        "journal_entry_builder",
        {"reviewed_allocations": {}, "invoice_document": {}},
        context={"correlation_id": "test-corr-1"},
    )
    assert result.ok
    assert "JOURNAL_ENTRY_READY" in result.perturbations_emitted
