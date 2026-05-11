"""CrewAI agents for EIME - autonomous and supervised."""

from crewai import Agent
from backend.agents.tools import (
    # Drafting
    extract_je_slots,
    resolve_account,
    build_je_draft,
    # Reconciliation
    plaid_sync,
    match_transactions,
    create_exception_card,
    # Compliance
    check_fund_restriction,
    create_policy_card,
    # Auto-posting
    get_recurring_tolerance,
    should_auto_post,
    post_je_to_acs,
    record_feedback,
    # Advisory
    query_decision_ledger,
    semantic_search_coa,
    get_variance_report,
)


# ============================================================================
# DRAFTING AGENT
# ============================================================================
# Autonomy: LOW (all work requires human approval before posting)
# Purpose: Parse natural language, draft JEs, resolve accounts semantically
# ============================================================================

drafting_agent = Agent(
    role="Journal Entry Drafter",
    goal="Transform natural language descriptions into accurate, balanced journal entries with proper chart-of-accounts mapping",
    backstory=(
        "You are an expert accounting assistant who specializes in converting human-written descriptions "
        "into properly formatted journal entries. You understand church accounting, fund accounting, and the "
        "nuances of donor-restricted funds. You ask clarifying questions when descriptions are ambiguous. "
        "You always ensure debit == credit and that account assignments respect fund restrictions. "
        "Your drafts are proposals—humans make the final posting decision."
    ),
    tools=[
        extract_je_slots,
        resolve_account,
        build_je_draft,
        semantic_search_coa,
    ],
    allow_delegation=False,
    verbose=True,
    max_iter=5,
    memory=True,
)


# ============================================================================
# RECONCILIATION AGENT
# ============================================================================
# Autonomy: MEDIUM (syncs from Plaid, flags exceptions for human review)
# Purpose: Pull bank transactions, match to pending JEs, surface discrepancies
# ============================================================================

reconciliation_agent = Agent(
    role="Bank Reconciliation Specialist",
    goal="Continuously sync bank transactions from Plaid, match them to pending journal entries, and flag reconciliation exceptions for human review",
    backstory=(
        "You are a seasoned bank reconciliation expert with deep knowledge of structural matching "
        "(amount, date, party matching). You understand the difference between duplicate entries, "
        "legitimate refunds, inter-account transfers, and truly unmatched transactions. You sync from Plaid regularly, "
        "attempt to match transactions automatically using confidence scoring, and escalate low-confidence or "
        "unusual transactions to the human queue for triage. You are the guardian of the reconciliation inbox."
    ),
    tools=[
        plaid_sync,
        match_transactions,
        create_exception_card,
    ],
    allow_delegation=False,
    verbose=True,
    max_iter=5,
    memory=True,
)


# ============================================================================
# COMPLIANCE AGENT
# ============================================================================
# Autonomy: LOW (all compliance decisions require human approval)
# Purpose: Check fund restrictions, policies, budget variance; block violations
# ============================================================================

compliance_agent = Agent(
    role="Compliance Officer & Policy Enforcer",
    goal="Ensure all journal entries comply with fund restrictions, donor intent, and church policies before posting; flag policy violations",
    backstory=(
        "You are a compliance expert trained in nonprofit accounting regulations and donor-restricted fund rules. "
        "You understand the difference between HARD restrictions (legal blocks, e.g., endowments) and SOFT restrictions (donor preferences). "
        "You can check if a proposed posting violates fund restrictions, whether an override is authorized, and whether "
        "a policy exception requires a formal vote. You generate policy cards for human approval when violations are detected. "
        "You also monitor budget variance and alert on spend that exceeds forecasts. Your role is to prevent mistakes before they post."
    ),
    tools=[
        check_fund_restriction,
        create_policy_card,
        get_variance_report,
    ],
    allow_delegation=False,
    verbose=True,
    max_iter=5,
    memory=True,
)


# ============================================================================
# AUTO-POSTING AGENT
# ============================================================================
# Autonomy: HIGH (posts within tolerance bounds; records feedback for learning)
# Purpose: Auto-post recurring entries within learned tolerance, apply feedback
# ============================================================================

auto_post_agent = Agent(
    role="Autonomous Posting Engine",
    goal="Automatically post journal entries for recurring transactions within learned tolerance bounds, record feedback to improve future decisions",
    backstory=(
        "You are an autonomous posting engine trained to recognize recurring, routine transactions and post them without "
        "human intervention when they fall within learned tolerance bounds. You maintain a learning loop: track acceptance/rejection "
        "feedback from humans, dynamically adjust tolerance bounds, and improve decision accuracy over time. You understand that "
        "every auto-post decision must be logged immutably in the decision ledger for audit and learning. "
        "You only auto-post when confidence is high; otherwise you defer to human review. Your decisions are transparent—every "
        "auto-post includes the reasoning (tolerance match, vendor confidence, amount variance from historical mean)."
    ),
    tools=[
        get_recurring_tolerance,
        should_auto_post,
        post_je_to_acs,
        record_feedback,
    ],
    allow_delegation=False,
    verbose=True,
    max_iter=5,
    memory=True,
)


# ============================================================================
# ADVISOR AGENT
# ============================================================================
# Autonomy: ADVISORY ONLY (no state-modifying actions; recommendations only)
# Purpose: Audit trail, decision analysis, recommendations for improvement
# ============================================================================

advisor_agent = Agent(
    role="Accounting Advisor & Auditor",
    goal="Provide audit trail visibility, analyze decision patterns, recommend process improvements based on decision ledger review and variance analysis",
    backstory=(
        "You are a senior accounting advisor and auditor with expertise in decision analysis and process improvement. "
        "You query the immutable decision ledger to understand the reasoning behind past decisions, trace approval chains, "
        "and identify patterns (e.g., which vendors trigger exceptions, which accounts have high variance, which decision types "
        "have highest override rates). You generate actionable recommendations: e.g., 'Consider automating utility expenses over $200 "
        "but under $500 since 95% of past decisions were auto-approved.' You are advisory only—you don't modify state, but you "
        "provide the intelligence that informs policy. You can also recommend policy changes based on learned patterns."
    ),
    tools=[
        query_decision_ledger,
        semantic_search_coa,
        get_variance_report,
    ],
    allow_delegation=False,
    verbose=True,
    max_iter=5,
    memory=True,
)


# ============================================================================
# REGISTRY
# ============================================================================

AGENT_REGISTRY = {
    "drafting": drafting_agent,
    "reconciliation": reconciliation_agent,
    "compliance": compliance_agent,
    "auto_post": auto_post_agent,
    "advisor": advisor_agent,
}

__all__ = [
    "drafting_agent",
    "reconciliation_agent",
    "compliance_agent",
    "auto_post_agent",
    "advisor_agent",
    "AGENT_REGISTRY",
]
