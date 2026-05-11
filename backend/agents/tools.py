"""CrewAI tools - wrappers around EIME backend functions."""

import logging
from typing import Dict, Any, Optional, List
from crewai.tools import tool
import json

logger = logging.getLogger(__name__)


# ============================================================================
# DRAFTING TOOLS
# ============================================================================

@tool("extract_je_slots")
def extract_je_slots(question: str) -> Dict[str, Any]:
    """Extract JE slots (from_account, to_account, amount, fund, memo) from natural language.
    
    Args:
        question: User's natural language request (e.g., "Draft a JE for the $247.50 Duke Energy bill")
    
    Returns:
        Dictionary with keys: from_account_hint, to_account_hint, amount, fund_hint, memo
    """
    from backend.tools.chat_router import _extract_je_slots_with_claude
    return _extract_je_slots_with_claude(question, None)


@tool("resolve_account")
def resolve_account(church_id: str, account_hint: str, fund_filter: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Semantic search to resolve account hint to a COA entry.
    
    Args:
        church_id: Church identifier
        account_hint: Free-text account description (e.g., "Duke Energy expense")
        fund_filter: Optional list of fund_ids to narrow search
    
    Returns:
        Account object with account_number, account_name, fund_id, or None if not found
    """
    from backend.tools.chat_router import _resolve_account
    return _resolve_account(church_id, account_hint, fund_filter) or {}


@tool("build_je_draft")
def build_je_draft(church_id: str, slots: Dict[str, Any], original_question: str) -> Dict[str, Any]:
    """Build a complete JournalEntry draft from extracted slots.
    
    Args:
        church_id: Church identifier
        slots: Dict with from_account_hint, to_account_hint, amount, fund_hint, memo
        original_question: Original user question for context
    
    Returns:
        JournalEntry dict with lines ready for review
    """
    from backend.tools.chat_router import _build_je_from_slots
    return _build_je_from_slots(church_id, slots, None, original_question)


# ============================================================================
# RECONCILIATION TOOLS
# ============================================================================

@tool("plaid_sync")
def plaid_sync(church_id: str) -> Dict[str, Any]:
    """Pull latest transactions from Plaid and sync to exceptions queue.
    
    Args:
        church_id: Church identifier
    
    Returns:
        Sync result with transaction count and new exceptions
    """
    import requests
    try:
        result = requests.post(
            f"http://localhost:8000/api/churches/{church_id}/plaid/sync",
            timeout=30
        )
        return result.json() if result.status_code == 200 else {"error": result.text}
    except Exception as e:
        return {"error": str(e)}


@tool("match_transactions")
def match_transactions(church_id: str, transaction_ids: List[str]) -> Dict[str, Any]:
    """Attempt structural matching of Plaid transactions to pending JEs.

    Args:
        church_id: Church identifier
        transaction_ids: List of Plaid transaction IDs to match

    Returns:
        Matches: {matched: [], unmatched: [], confidence_by_id: {}}
    """
    import requests
    try:
        result = requests.post(
            f"http://localhost:8000/api/churches/{church_id}/reconciliation/match",
            json={"transaction_ids": transaction_ids},
            timeout=30
        )
        return result.json() if result.status_code == 200 else {
            "matched": [],
            "unmatched": transaction_ids,
            "confidence_by_id": {tid: 0.0 for tid in transaction_ids},
            "error": result.text,
        }
    except Exception as e:
        return {
            "matched": [],
            "unmatched": transaction_ids,
            "confidence_by_id": {tid: 0.0 for tid in transaction_ids},
            "error": str(e),
        }


@tool("create_exception_card")
async def create_exception_card(church_id: str, exception_type: str, title: str, description: str, evidence: Dict[str, Any]) -> str:
    """Flag a transaction as an exception for human review.

    Writes to CardStore as single source of truth for all queries.

    Args:
        church_id: Church identifier
        exception_type: Type of exception (e.g., "RECONCILIATION", "AMBIGUOUS_VENDOR")
        title: Short title for the exception
        description: Detailed description
        evidence: JSON evidence (e.g., {"txn_id": "...", "confidence": 0.45})

    Returns:
        Exception card ID
    """
    from backend.membrane.stores.exceptions import ExceptionCardStore

    card_id = await ExceptionCardStore.create(
        church_id,
        exception_type,
        title,
        description,
        evidence=evidence,
    )

    return card_id


# ============================================================================
# COMPLIANCE TOOLS
# ============================================================================

@tool("check_fund_restriction")
def check_fund_restriction(church_id: str, fund_id: str, actor_role: Optional[str] = None) -> Dict[str, Any]:
    """Check if a fund posting violates donor restrictions.

    Args:
        church_id: Church identifier
        fund_id: Fund identifier
        actor_role: Role of the actor attempting the action (for override checks)

    Returns:
        {violation: bool, type: 'HARD'|'SOFT'|None, reason: str, override_role: str|None}
    """
    from backend.db.fund_restriction_store import check_restriction_violation
    return check_restriction_violation(church_id, fund_id, actor_role)


@tool("create_policy_card")
async def create_policy_card(church_id: str, policy_id: str, title: str, description: str) -> str:
    """Create a policy card requiring human approval.

    Writes to CardStore as single source of truth for all queries.

    Args:
        church_id: Church identifier
        policy_id: Policy identifier
        title: Card title
        description: Policy violation description

    Returns:
        Policy card ID
    """
    from backend.membrane.stores.policies import PolicyCardStore

    card_id = await PolicyCardStore.create(
        church_id,
        policy_id,
        title,
        description,
        policy_rules={},
        effective_date="",
        enforcement_level="warning",
    )

    return card_id


# ============================================================================
# AUTO-POSTING TOOLS
# ============================================================================

@tool("get_recurring_tolerance")
def get_recurring_tolerance(recurring_id: str) -> Dict[str, Any]:
    """Get learned tolerance bounds for a recurring vendor.

    Args:
        recurring_id: Recurring entry identifier

    Returns:
        {tolerance_low, tolerance_high, acceptance_count, rejection_count, acceptance_rate}
    """
    from backend.db.recurring_learning_store import get_tolerance_bounds
    return get_tolerance_bounds(recurring_id) or {
        "tolerance_low": 0.0,
        "tolerance_high": 0.0,
        "acceptance_count": 0,
        "rejection_count": 0,
        "acceptance_rate": 0.5,
    }


@tool("should_auto_post")
def should_auto_post(recurring_id: str, proposed_amount: float) -> Dict[str, Any]:
    """Check if a recurring JE amount should auto-post based on tolerance.

    Args:
        recurring_id: Recurring entry identifier
        proposed_amount: Proposed transaction amount

    Returns:
        {should_auto_post: bool, reason: str, bounds: {...}}
    """
    from backend.db.recurring_learning_store import should_auto_post as check
    return check(recurring_id, proposed_amount)


@tool("post_je_to_acs")
def post_je_to_acs(je_id: str, church_id: str) -> Dict[str, Any]:
    """Post a JE to ACS Realm via Playwright automation.

    Args:
        je_id: Journal entry ID
        church_id: Church identifier

    Returns:
        {success: bool, acs_reference: str, error_message: str|None}
    """
    import requests
    try:
        result = requests.post(
            f"http://localhost:8000/api/jes/{je_id}/post",
            json={"church_id": church_id},
            timeout=60
        )
        if result.status_code == 200:
            data = result.json()
            return {
                "success": True,
                "acs_reference": data.get("acs_reference"),
                "error_message": None,
            }
        else:
            return {
                "success": False,
                "acs_reference": None,
                "error_message": result.text,
            }
    except Exception as e:
        return {
            "success": False,
            "acs_reference": None,
            "error_message": str(e),
        }


@tool("record_feedback")
def record_feedback(recurring_id: str, accepted: bool, tolerance_low: float, tolerance_high: float) -> None:
    """Record user acceptance/rejection feedback for a recurring JE.

    Args:
        recurring_id: Recurring entry identifier
        accepted: True if user approved, False if rejected
        tolerance_low: Current lower tolerance bound
        tolerance_high: Current upper tolerance bound

    Returns:
        None
    """
    from backend.db.recurring_learning_store import record_tolerance_feedback
    record_tolerance_feedback(recurring_id, accepted, tolerance_low, tolerance_high)


# ============================================================================
# ADVISORY/AUDIT TOOLS
# ============================================================================

@tool("query_decision_ledger")
def query_decision_ledger(church_id: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Query the immutable decision ledger for evidence.

    Args:
        church_id: Church identifier
        filters: Query filters (e.g., {"je_id": "...", "event_type": "DECISION_RECORDED"})

    Returns:
        List of decision ledger events
    """
    import requests
    try:
        result = requests.get(
            f"http://localhost:8000/api/events",
            params={**filters, "church_id": church_id},
            timeout=30
        )
        return result.json() if result.status_code == 200 else []
    except Exception as e:
        print(f"Error querying decision ledger: {e}")
        return []


@tool("semantic_search_coa")
def semantic_search_coa(church_id: str, query: str, k: int = 5) -> List[Dict[str, Any]]:
    """Semantic search the chart of accounts.
    
    Args:
        church_id: Church identifier
        query: Search query (e.g., "utility expenses")
        k: Number of results to return
    
    Returns:
        List of matching COA accounts with similarity scores
    """
    from backend.tools.coa_store import semantic_search
    return semantic_search(church_id, query, k) or []


@tool("get_variance_report")
def get_variance_report(church_id: str, fund_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Get budget variance report.
    
    Args:
        church_id: Church identifier
        fund_ids: Optional filter to specific funds
    
    Returns:
        Budget variance analysis with alerts
    """
    import requests
    try:
        params = {"fund_ids": ",".join(fund_ids)} if fund_ids else {}
        result = requests.get(
            f"http://localhost:8000/api/churches/{church_id}/budget/variance-report",
            params=params,
            timeout=30
        )
        return result.json() if result.status_code == 200 else {"error": result.text}
    except Exception as e:
        return {"error": str(e)}
