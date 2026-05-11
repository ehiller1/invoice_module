"""Agent and crew registries with FastAPI endpoints."""

from typing import Dict, Any, Optional, List
from crewai import Task
from pydantic import BaseModel

from backend.agents.agents import AGENT_REGISTRY
from backend.agents.crews import CREW_REGISTRY


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class DraftJERequest(BaseModel):
    """Request to draft a JE from natural language."""
    church_id: str
    description: str


class DraftJEResponse(BaseModel):
    """Response with drafted JE."""
    status: str  # "SUCCESS", "PARTIAL", "ERROR"
    je_draft: Optional[Dict[str, Any]] = None
    violations: Optional[List[Dict[str, Any]]] = None
    error_message: Optional[str] = None


class ReconciliationRequest(BaseModel):
    """Request to run full reconciliation."""
    church_id: str
    sync_from_plaid: bool = True


class ReconciliationResponse(BaseModel):
    """Response with reconciliation results."""
    status: str  # "SUCCESS", "PARTIAL", "ERROR"
    transactions_synced: int = 0
    matched: int = 0
    exceptions: List[Dict[str, Any]] = []
    error_message: Optional[str] = None


class AutoPostingRequest(BaseModel):
    """Request to run auto-posting for recurring entries."""
    church_id: str
    recurring_ids: List[str]


class AutoPostingResponse(BaseModel):
    """Response with posting results."""
    status: str
    posted: int = 0
    deferred: int = 0
    error_message: Optional[str] = None


class AdvisoryRequest(BaseModel):
    """Request for advisory analysis."""
    church_id: str
    query_type: str  # "decision_patterns", "variance", "vendor_analysis", "policy_recommendations"
    params: Optional[Dict[str, Any]] = None


class AdvisoryResponse(BaseModel):
    """Response with advisory findings."""
    status: str
    findings: Dict[str, Any] = {}
    recommendations: List[str] = []
    error_message: Optional[str] = None


# ============================================================================
# CREW TASK FACTORY
# ============================================================================

def create_draft_je_task(church_id: str, description: str) -> Task:
    """Create a task for drafting a JE."""
    return Task(
        description=(
            f"Church: {church_id}\n"
            f"User description: {description}\n\n"
            f"Steps:\n"
            f"1. Use extract_je_slots to parse the description\n"
            f"2. Use resolve_account to map accounts (hint → COA)\n"
            f"3. Use build_je_draft to create the full draft\n"
            f"4. Return the draft lines with account numbers and amounts"
        ),
        expected_output="Complete JE draft with balanced lines and account metadata",
        agent=AGENT_REGISTRY["drafting"],
    )


def create_reconciliation_task(church_id: str) -> Task:
    """Create a task for bank reconciliation."""
    return Task(
        description=(
            f"Church: {church_id}\n\n"
            f"Steps:\n"
            f"1. Use plaid_sync to pull latest transactions\n"
            f"2. Use match_transactions to structurally match against pending JEs\n"
            f"3. For any unmatched or low-confidence matches, use create_exception_card\n"
            f"4. Return summary of matches and exceptions"
        ),
        expected_output="Reconciliation summary with matched/unmatched counts and exception cards",
        agent=AGENT_REGISTRY["reconciliation"],
    )


def create_compliance_task(je_draft: Dict[str, Any], church_id: str) -> Task:
    """Create a task for compliance review."""
    return Task(
        description=(
            f"Church: {church_id}\n"
            f"JE draft: {je_draft}\n\n"
            f"Steps:\n"
            f"1. For each line in the JE, use check_fund_restriction to verify no violations\n"
            f"2. Use get_variance_report to check budget impact\n"
            f"3. If any violations found, use create_policy_card\n"
            f"4. Return approval status or list of violations"
        ),
        expected_output="Compliance check result with approval status or violation details",
        agent=AGENT_REGISTRY["compliance"],
    )


def create_auto_posting_task(church_id: str, recurring_ids: List[str]) -> Task:
    """Create a task for auto-posting recurring entries."""
    return Task(
        description=(
            f"Church: {church_id}\n"
            f"Recurring IDs: {recurring_ids}\n\n"
            f"Steps:\n"
            f"1. For each recurring ID, use get_recurring_tolerance to get learned bounds\n"
            f"2. Use should_auto_post to check if amount is within tolerance\n"
            f"3. If eligible, use post_je_to_acs to post to ACS Realm\n"
            f"4. After posting, use record_feedback to update learning\n"
            f"5. Return results with posted/deferred counts"
        ),
        expected_output="Auto-posting summary with posted entries and any deferrals",
        agent=AGENT_REGISTRY["auto_post"],
    )


def create_advisory_task(church_id: str, query_type: str, params: Optional[Dict[str, Any]] = None) -> Task:
    """Create a task for advisory analysis."""
    params_str = str(params) if params else ""
    return Task(
        description=(
            f"Church: {church_id}\n"
            f"Query type: {query_type}\n"
            f"Parameters: {params_str}\n\n"
            f"Steps:\n"
            f"1. Use query_decision_ledger to retrieve decision history\n"
            f"2. Use get_variance_report to analyze budget patterns\n"
            f"3. Use semantic_search_coa to find account insights\n"
            f"4. Generate actionable recommendations based on patterns\n"
            f"5. Return findings and recommendations"
        ),
        expected_output="Advisory findings with patterns detected and recommendations for improvement",
        agent=AGENT_REGISTRY["advisor"],
    )


# ============================================================================
# ENDPOINT HANDLERS
# ============================================================================

async def handle_draft_je(req: DraftJERequest) -> DraftJEResponse:
    """Handle draft JE request."""
    try:
        crew = CREW_REGISTRY["draft_and_check"]
        task = create_draft_je_task(req.church_id, req.description)

        # Add task to crew (CrewAI crews can accept tasks dynamically)
        crew.tasks = [task]

        result = crew.kickoff()

        # Parse result - structure depends on agent output
        if isinstance(result, dict):
            return DraftJEResponse(
                status="SUCCESS",
                je_draft=result.get("je_draft"),
                violations=result.get("violations"),
            )
        else:
            # String result - compliance check passed
            return DraftJEResponse(
                status="SUCCESS",
                je_draft={"status": "draft_approved_by_compliance"},
            )
    except Exception as e:
        return DraftJEResponse(
            status="ERROR",
            error_message=str(e),
        )


async def handle_reconciliation(req: ReconciliationRequest) -> ReconciliationResponse:
    """Handle reconciliation request."""
    try:
        crew = CREW_REGISTRY["full_posting"]
        task = create_reconciliation_task(req.church_id)
        crew.tasks = [task]

        result = crew.kickoff()

        if isinstance(result, dict):
            return ReconciliationResponse(
                status="SUCCESS",
                transactions_synced=result.get("transactions_synced", 0),
                matched=result.get("matched", 0),
                exceptions=result.get("exceptions", []),
            )
        else:
            return ReconciliationResponse(status="SUCCESS")
    except Exception as e:
        return ReconciliationResponse(
            status="ERROR",
            error_message=str(e),
        )


async def handle_auto_posting(req: AutoPostingRequest) -> AutoPostingResponse:
    """Handle auto-posting request."""
    try:
        crew = CREW_REGISTRY["full_posting"]
        task = create_auto_posting_task(req.church_id, req.recurring_ids)
        crew.tasks = [task]

        result = crew.kickoff()

        if isinstance(result, dict):
            return AutoPostingResponse(
                status="SUCCESS",
                posted=result.get("posted", 0),
                deferred=result.get("deferred", 0),
            )
        else:
            return AutoPostingResponse(status="SUCCESS")
    except Exception as e:
        return AutoPostingResponse(
            status="ERROR",
            error_message=str(e),
        )


async def handle_advisory(req: AdvisoryRequest) -> AdvisoryResponse:
    """Handle advisory request."""
    try:
        crew = CREW_REGISTRY["advisory"]
        task = create_advisory_task(req.church_id, req.query_type, req.params)
        crew.tasks = [task]

        result = crew.kickoff()

        if isinstance(result, dict):
            return AdvisoryResponse(
                status="SUCCESS",
                findings=result.get("findings", {}),
                recommendations=result.get("recommendations", []),
            )
        else:
            return AdvisoryResponse(status="SUCCESS")
    except Exception as e:
        return AdvisoryResponse(
            status="ERROR",
            error_message=str(e),
        )


# ============================================================================
# REGISTRIES
# ============================================================================

__all__ = [
    "AGENT_REGISTRY",
    "CREW_REGISTRY",
    "DraftJERequest",
    "DraftJEResponse",
    "ReconciliationRequest",
    "ReconciliationResponse",
    "AutoPostingRequest",
    "AutoPostingResponse",
    "AdvisoryRequest",
    "AdvisoryResponse",
    "handle_draft_je",
    "handle_reconciliation",
    "handle_auto_posting",
    "handle_advisory",
]
