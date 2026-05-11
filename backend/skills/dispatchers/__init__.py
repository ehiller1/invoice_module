"""Archetype dispatchers (Phase 3).

Each dispatcher knows how to invoke a specific archetype's skills. Dispatchers
are deliberately small and side-effect-light: they look up the SKILL.md
metadata via the registry, route to an optional `entry.py` if present, and
otherwise return a structured stub result so downstream stages (Flow, tests)
have something deterministic to consume.
"""
from .base import ArchetypeDispatcher, DispatchResult
from .worker_dispatcher import WorkerDispatcher
from .researcher_dispatcher import ResearcherDispatcher
from .reviewer_dispatcher import ReviewerDispatcher
from .conversationalist_dispatcher import ConversationalistDispatcher
from .orchestrator_dispatcher import OrchestratorDispatcher

__all__ = [
    "ArchetypeDispatcher",
    "DispatchResult",
    "WorkerDispatcher",
    "ResearcherDispatcher",
    "ReviewerDispatcher",
    "ConversationalistDispatcher",
    "OrchestratorDispatcher",
]
