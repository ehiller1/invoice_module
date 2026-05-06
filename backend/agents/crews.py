"""CrewAI crews and agents for the EIME pipeline.

Each archetype is a domain-agnostic execution shell; expertise lives in SKILL.md files
loaded at runtime by the skill registry (per FRS §3.1 architectural principles).
"""
from __future__ import annotations
from crewai import Agent, Crew, Task, Process
from crewai.tools import BaseTool
from pydantic import Field
from typing import Any, List, Optional
import json

from ..tools.skill_registry import get_registry


# ===== CrewAI Tool wrappers =====

class SkillSearchTool(BaseTool):
    name: str = "skill_search_tool"
    description: str = "Discover available SKILL.md files by archetype or keyword."

    def _run(self, archetype: Optional[str] = None) -> str:
        registry = get_registry()
        results = registry.search(archetype=archetype)
        return json.dumps(results, indent=2)


class SkillLoadTool(BaseTool):
    name: str = "skill_load_tool"
    description: str = "Load the full body of a SKILL.md file by skill_name."

    def _run(self, skill_name: str) -> str:
        registry = get_registry()
        try:
            body = registry.load_body(skill_name)
            meta = registry.get(skill_name) or {}
            return f"# {skill_name}\n\n{body}"
        except KeyError:
            return f"Skill '{skill_name}' not found in registry."


skill_search_tool = SkillSearchTool()
skill_load_tool = SkillLoadTool()


# ===== Agent factory =====

def make_orchestrator() -> Agent:
    return Agent(
        role="Invoice Processing Orchestrator",
        goal=(
            "Discover the correct sequence of skills for the uploaded document type "
            "and produce a typed execution plan. You do not perform any accounting work yourself."
        ),
        backstory=(
            "You are a domain-agnostic workflow planner. All accounting expertise lives in "
            "SKILL.md files you discover at runtime via the skill registry. Your job is to "
            "query the registry, understand what skills are available, and emit a correct "
            "execution plan for the downstream crews."
        ),
        tools=[skill_search_tool, skill_load_tool],
        verbose=False,
        allow_delegation=False,
    )


def make_researcher() -> Agent:
    return Agent(
        role="Accounting Context Researcher",
        goal=(
            "Load the church's Chart of Accounts, fund configuration, allocation schedules, "
            "and denomination-specific rules. Return a complete AccountingContext."
        ),
        backstory=(
            "You are a general-purpose researcher who specialises in loading and indexing "
            "church accounting configurations. You never hard-code accounting rules — all "
            "rules come from the coa_reference_loader and vendor_history_lookup skills."
        ),
        tools=[skill_load_tool],
        verbose=False,
        allow_delegation=False,
    )


def make_worker() -> Agent:
    return Agent(
        role="Invoice Processing Worker",
        goal=(
            "Execute discrete mapping tasks: PDF extraction, line-item classification, "
            "GL account recommendation, allocation computation, and journal entry drafting."
        ),
        backstory=(
            "You are a general-purpose worker. All accounting logic you apply comes from "
            "the skill you loaded for this step. You never invent GL accounts or fund rules "
            "from your training — only what the skill and accounting context specify."
        ),
        tools=[skill_load_tool],
        verbose=False,
        allow_delegation=False,
    )


def make_reviewer() -> Agent:
    return Agent(
        role="Allocation Quality Reviewer",
        goal=(
            "Validate every draft posting against fund restriction rules and the church's "
            "expenditure policies. Approve, request revision, or escalate for HITL review."
        ),
        backstory=(
            "You are a quality reviewer with knowledge of nonprofit fund accounting (GAAP ASC 958). "
            "You apply the allocation_reviewer skill's rules strictly — if a restricted fund "
            "purpose does not match the expense, you always escalate regardless of confidence."
        ),
        tools=[skill_load_tool],
        verbose=False,
        allow_delegation=False,
    )


def make_conversationalist() -> Agent:
    return Agent(
        role="HITL Gate Coordinator",
        goal=(
            "Surface ambiguous or high-value line items to the appropriate human reviewer "
            "via structured prompts. Collect decisions and return approved allocations to the Flow."
        ),
        backstory=(
            "You coordinate the human-in-the-loop review gate. You identify the correct "
            "reviewer role (Treasurer, Finance Committee, Personnel Committee), present "
            "structured review cards, and collect decisions. You never approve restricted "
            "fund postings without documented human sign-off."
        ),
        tools=[skill_load_tool],
        verbose=False,
        allow_delegation=False,
    )


def make_membrane() -> Agent:
    return Agent(
        role="Accounting Domain Distiller",
        goal=(
            "Package the completed JournalEntry for the Embark Accounting ledger domain. "
            "Strip internal agent reasoning artifacts and emit the AccountingDomainEvent."
        ),
        backstory=(
            "You enforce the domain boundary. You validate completeness, ensure the entry is "
            "balanced, strip intermediate workflow states, and emit the event. You never emit "
            "an unbalanced or incomplete journal entry."
        ),
        tools=[skill_load_tool],
        verbose=False,
        allow_delegation=False,
    )


# ===== Crew factory =====

def make_orchestrator_crew(pdf_path: str, church_id: str, document_type: str) -> tuple[Crew, Task]:
    agent = make_orchestrator()
    task = Task(
        description=(
            f"Using skill_search_tool, discover all available skills. "
            f"Produce a JSON execution plan for processing document_type='{document_type}' "
            f"at path '{pdf_path}' for church '{church_id}'. "
            f"Return a JSON array of steps: {{archetype, skill_name, inputs, depends_on}}."
        ),
        expected_output="JSON execution plan array",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    return crew, task


def make_researcher_crew(church_id: str, fiscal_year: int) -> tuple[Crew, Task]:
    agent = make_researcher()
    task = Task(
        description=(
            f"Load and validate the accounting context for church '{church_id}' "
            f"fiscal year {fiscal_year} using the coa_reference_loader skill. "
            f"Return summary of accounts count, funds, and any warnings."
        ),
        expected_output="AccountingContext summary with account/fund counts and warnings",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    return crew, task
