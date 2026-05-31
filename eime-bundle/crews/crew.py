# EIME bundle — CrewAI crew scaffold
#
# Module:     eime
# Domain:     ein.parish.financial_intelligence
# Category:   parish_tier_agent
# Keywords:   parish financial intelligence, invoice gl mapping, fund accounting compliance,
#             journal entry approval, bank reconciliation matching, autonomous recurring posting
#
# Mirrors the 7-crew structure declared in agents/agents.yaml:
#   1. invoice_ingestion_mapping  — UC-1, 7-agent sequential extract→map→build crew
#   2. journal_entry_compliance   — UC-2, drafting + fund/policy compliance gate
#   3. approval_hitl              — UC-3, multi-tier HITL approval chain
#   4. bank_reconciliation        — UC-4, Plaid match + dedup + exception
#   5. autonomous_posting         — UC-5, recurring auto-post within tolerance
#   6. advisory_nba              — UC-6, recommendation cards + scenario preview
#   7. conversational_routing     — UC-7, intent classification + dispatch
#
# The 6 membrane archetypes (orchestrator, researcher, worker, reviewer,
# conversationalist, membrane) from backend/agents/crews.py are runtime patterns,
# not domain agents; they back the crew constructors below rather than appearing
# as standalone agent rows in agents.yaml.

from crewai import Agent, Task, Crew, Flow
from crewai.flow.flow import listen, router, start
import yaml
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent.parent
AGENTS_CFG = yaml.safe_load(open(BUNDLE_ROOT / "agents" / "agents.yaml"))
TASKS_CFG = yaml.safe_load(open(BUNDLE_ROOT / "tasks" / "tasks.yaml"))


def _find_agent(agent_id: str) -> dict:
    for crew in AGENTS_CFG["crews"].values():
        for a in crew["agents"]:
            if a["id"] == agent_id:
                return a
    raise KeyError(agent_id)


def _find_task(task_id: str) -> dict:
    for t in TASKS_CFG["tasks"]:
        if t["id"] == task_id:
            return t
    raise KeyError(task_id)


def _build_agent(agent_id: str) -> Agent:
    cfg = _find_agent(agent_id)
    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg.get("backstory", ""),
        verbose=False,
        allow_delegation=False,
    )


def _build_task(task_id: str) -> Task:
    cfg = _find_task(task_id)
    return Task(
        description=cfg["description"],
        expected_output=cfg["expected_output"],
        agent=_build_agent(cfg["agent_id"]),
    )


def _crew(agent_ids, task_ids, process="sequential") -> Crew:
    return Crew(
        agents=[_build_agent(a) for a in agent_ids],
        tasks=[_build_task(t) for t in task_ids],
        verbose=False,
    )


# ---------- Crew constructors (one per agents.yaml crew) ----------

def invoice_ingestion_mapping_crew() -> Crew:
    return _crew(
        ["invoice_extractor", "coa_loader", "expense_classifier", "gl_account_mapper",
         "risk_fraud_officer", "allocation_reviewer", "journal_entry_builder"],
        ["extract_invoice", "load_coa", "classify_lines", "map_to_gl",
         "assess_risk_budget", "review_allocations", "build_je"],
    )


def journal_entry_compliance_crew() -> Crew:
    return _crew(
        ["journal_entry_drafter", "compliance_officer"],
        ["draft_je", "enforce_compliance"],
    )


def approval_hitl_crew() -> Crew:
    return _crew(["hitl_gate_coordinator"], ["drive_approval_chain"])


def bank_reconciliation_crew() -> Crew:
    return _crew(["reconciliation_specialist"], ["reconcile_bank_feed"])


def autonomous_posting_crew() -> Crew:
    return _crew(["autonomous_posting_engine"], ["auto_post_recurring"])


def advisory_nba_crew() -> Crew:
    return _crew(["accounting_advisor"], ["surface_recommendation"])


def conversational_routing_crew() -> Crew:
    return _crew(["intent_router"], ["route_intent"])


# ---------- Top-level Flow: routes inbound perturbations to crews ----------

class EimeFlow(Flow):
    """In-process router. Mesh-side subscriptions live in mesh/mesh_config.yaml."""

    @start()
    def receive(self, perturbation: dict):
        return perturbation

    @router(receive)
    def route(self, perturbation: dict):
        ptype = (perturbation or {}).get("type", "")
        return {
            "INVOICE_INGESTED": "invoice_ingestion_mapping",
            "JOURNAL_ENTRY_READY": "journal_entry_compliance",
            "APPROVAL_DEADLINE_PRESSURE": "approval_hitl",
            "HITL_ESCALATION": "approval_hitl",
            "RECONCILIATION_EXCEPTION": "bank_reconciliation",
        }.get(ptype, "conversational_routing")
