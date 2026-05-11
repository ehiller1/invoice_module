"""SkillRouter — invoke any skill by name, routing to the appropriate dispatcher.

Phase 3 of the membrane integration plan. The router is the single entry
point used by the CrewAI Flow, MVP agent wrappers, and (eventually) cabinet
members.

Design:
  - Pure dispatch; no posting side effects.
  - Returns a `DispatchResult` (dataclass) so callers see a uniform shape.
  - Optional `publisher` injection lets the router emit ImpactSignals for any
    `perturbations_emitted` declared in the skill's frontmatter.
  - Optional `mvp_agents` registry allows the router to invoke MVP CrewAI
    agents (drafting, reconciliation, compliance, auto-post, advisor) by
    skill_name, bridging the existing agent layer into the skill library.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from backend.tools.skill_registry import SkillRegistry, get_registry

from .dispatchers import (
    ArchetypeDispatcher,
    ConversationalistDispatcher,
    DispatchResult,
    OrchestratorDispatcher,
    ResearcherDispatcher,
    ReviewerDispatcher,
    WorkerDispatcher,
)


MVPAgentCallable = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]


class SkillRouter:
    """Routes `invoke(skill_name, inputs, context)` to the correct dispatcher."""

    def __init__(
        self,
        registry: Optional[SkillRegistry] = None,
        publisher: Optional[Any] = None,
    ) -> None:
        self.registry = registry or get_registry()
        self.publisher = publisher
        self._dispatchers: Dict[str, ArchetypeDispatcher] = {
            "worker":            WorkerDispatcher(self.registry),
            "researcher":        ResearcherDispatcher(self.registry),
            "reviewer":          ReviewerDispatcher(self.registry),
            "conversationalist": ConversationalistDispatcher(self.registry),
            "orchestrator":      OrchestratorDispatcher(self.registry),
            # Membrane-archetype skills are dispatched by the worker dispatcher
            # for now (single transformation, no human in the loop).
            "membrane":          WorkerDispatcher(self.registry),
        }
        # MVP agent wrappers (drafting_agent, reconciliation_agent, ...).
        self._mvp_agents: Dict[str, MVPAgentCallable] = {}

    # ------------------------------------------------------------------- API
    def register_mvp_agent(self, skill_name: str, callable_: MVPAgentCallable) -> None:
        """Bind an async callable as the implementation for an MVP-agent skill."""
        self._mvp_agents[skill_name] = callable_

    def list_skills(self, archetype: Optional[str] = None):
        return self.registry.search(archetype=archetype)

    async def invoke(
        self,
        skill_name: str,
        inputs: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> DispatchResult:
        inputs = inputs or {}
        context = context or {}

        # MVP agent fast-path: a registered callable wins over the archetype dispatcher.
        if skill_name in self._mvp_agents:
            try:
                output = await self._mvp_agents[skill_name](inputs, context)
            except Exception as exc:
                return DispatchResult(
                    skill_name=skill_name,
                    archetype="mvp_agent",
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if not isinstance(output, dict):
                output = {"value": output}
            return DispatchResult(
                skill_name=skill_name,
                archetype="mvp_agent",
                ok=True,
                output=output,
            )

        record = self.registry.get(skill_name)
        if not record:
            return DispatchResult(
                skill_name=skill_name,
                archetype="unknown",
                ok=False,
                error=f"skill not found: {skill_name}",
            )
        dispatcher = self._dispatchers.get(record["archetype"])
        if not dispatcher:
            return DispatchResult(
                skill_name=skill_name,
                archetype=record["archetype"],
                ok=False,
                error=f"no dispatcher for archetype {record['archetype']!r}",
            )
        result = await dispatcher.invoke(skill_name, inputs, context)

        # Optional publish of declared perturbations.
        if result.ok and self.publisher is not None and result.perturbations_emitted:
            await self._emit_perturbations(result, context)
        return result

    # -------------------------------------------------------------- internal
    async def _emit_perturbations(
        self, result: DispatchResult, context: Dict[str, Any]
    ) -> None:
        try:
            from backend.membrane.envelope import ImpactSignal
            from backend.membrane.perturbations import get_perturbation
        except Exception:
            return
        for name in result.perturbations_emitted:
            try:
                pert = get_perturbation(name)
            except KeyError:
                continue
            envelope = ImpactSignal(
                signal_id=pert.id,
                signal_name=pert.name,
                event_id=str(uuid.uuid4()),
                occurred_at=datetime.now(tz=timezone.utc),
                privacy_class=pert.privacy_class,
                crosses_membrane=pert.crosses_membrane,
                target_channel=pert.target_channel,
                payload={"skill": result.skill_name, "source_archetype": result.archetype},
                source=f"skill:{result.skill_name}",
                correlation_id=context.get("correlation_id"),
                retention=pert.default_retention,
            )
            try:
                await self.publisher.publish_signal(envelope)
            except Exception:
                # Best-effort emission; the Flow level handles retries.
                continue


_router: Optional[SkillRouter] = None


def get_router() -> SkillRouter:
    global _router
    if _router is None:
        _router = SkillRouter()
    return _router


def reset_router_for_tests() -> None:
    global _router
    _router = None


__all__ = ["SkillRouter", "get_router", "reset_router_for_tests"]
