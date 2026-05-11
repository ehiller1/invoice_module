"""Phase 13: NBA Crew — CrewAI-backed Next Best Action Generation.

Three-agent crew:
1. Analyst Agent — consumes perturbations, queries Card Store for context
2. Recommender Agent — ranks candidates, generates Recommendation Cards
3. Risk Assessor Agent — evaluates financial/policy/compliance risk
"""

import asyncio
import logging
from typing import Optional

from crewai import Agent, Task, Crew, Process

logger = logging.getLogger(__name__)


class NBACrewFactory:
    """Factory for creating and managing the NBA crew."""

    @staticmethod
    def create_analyst_agent() -> Agent:
        """Create Analyst Agent.

        Identifies recommendation candidates from perturbations.
        Queries Card Store for context (recent decisions, projections, violations).
        """
        return Agent(
            role="Financial Analyst",
            goal="Identify opportunities for financial optimization and risk mitigation",
            backstory=(
                "You are a financial analyst specializing in organizational accounting and budgeting. "
                "You excel at identifying inefficiencies, budget overages, and policy violations. "
                "You have access to recent cabinet decisions, budget projections, and transaction history. "
                "Your role is to surface actionable opportunities that need leadership attention."
            ),
            tools=[],  # Tools injected at crew invocation
            verbose=True,
        )

    @staticmethod
    def create_recommender_agent() -> Agent:
        """Create Recommender Agent.

        Generates ranked recommendations with impact projections.
        Creates Recommendation Cards with alternatives and confidence scores.
        """
        return Agent(
            role="Financial Advisor",
            goal="Generate prioritized, actionable financial recommendations",
            backstory=(
                "You are an expert financial advisor with deep knowledge of organizational accounting. "
                "You synthesize analyst findings into concrete recommendations with clear impact projections. "
                "You rank recommendations by feasibility, impact, and risk. "
                "You always provide multiple alternatives and clear reasoning. "
                "Your recommendations include specific GL impacts, affected accounts, and decision prerequisites."
            ),
            tools=[],  # Tools injected at crew invocation
            verbose=True,
        )

    @staticmethod
    def create_risk_assessor_agent() -> Agent:
        """Create Risk Assessor Agent.

        Evaluates financial, policy, and compliance risk of recommendations.
        Flags high-risk recommendations for manual review.
        """
        return Agent(
            role="Risk Assessment Officer",
            goal="Identify and mitigate financial and compliance risks",
            backstory=(
                "You are a risk assessment specialist focused on financial governance and compliance. "
                "You evaluate recommendations against organizational policies, budgetary constraints, and regulatory requirements. "
                "You identify hidden risks, interdependencies, and unintended consequences. "
                "You flag high-risk recommendations for escalation and recommend mitigations for medium-risk items."
            ),
            tools=[],  # Tools injected at crew invocation
            verbose=True,
        )

    @staticmethod
    def create_crew() -> Crew:
        """Create the full NBA crew with three agents."""
        analyst = NBACrewFactory.create_analyst_agent()
        recommender = NBACrewFactory.create_recommender_agent()
        risk_assessor = NBACrewFactory.create_risk_assessor_agent()

        # Define tasks in sequence
        analysis_task = Task(
            description=(
                "Analyze the current financial situation and identify opportunities for improvement. "
                "Consider: Budget overages, exceptions, policy violations, historical decision patterns. "
                "List candidate recommendations with trigger information."
            ),
            agent=analyst,
            expected_output=(
                "List of candidate recommendations with: trigger_type, trigger_ids, affected accounts, "
                "projected impact, and confidence rationale."
            ),
        )

        recommendation_task = Task(
            description=(
                "Based on the analyst's findings, generate prioritized recommendations. "
                "For each recommendation: provide title, description, projected GL impact, confidence score, "
                "priority level, reasoning, and 2-3 alternatives with their trade-offs."
            ),
            agent=recommender,
            expected_output=(
                "Ranked list of recommendations (JSON) with: recommendation_id, title, description, "
                "affected_accounts, projected_impact, confidence, priority, reasoning, alternatives."
            ),
        )

        risk_task = Task(
            description=(
                "Evaluate the recommended actions for financial, policy, and compliance risk. "
                "For each recommendation: identify risk factors, risk level (low/medium/high/critical), "
                "prerequisites, and any mitigating actions. Flag high-risk items for escalation."
            ),
            agent=risk_assessor,
            expected_output=(
                "Risk assessment (JSON) with: risk_level, risk_factors, prerequisites, "
                "mitigation_actions, and escalation_required flag for each recommendation."
            ),
        )

        # Create crew with sequential process
        crew = Crew(
            agents=[analyst, recommender, risk_assessor],
            tasks=[analysis_task, recommendation_task, risk_task],
            process=Process.SEQUENTIAL,
            verbose=True,
        )

        return crew

    @staticmethod
    async def invoke_crew(
        trigger_type: str,
        context: dict,
        tools: list = None,
    ) -> dict:
        """Invoke NBA crew asynchronously.

        Args:
            trigger_type: Type of trigger (budget_overage, exception, etc.)
            context: Cabinet context with recent decisions, projections, violations
            tools: List of tools available to agents

        Returns:
            Dict with recommendations, risk assessments, and decision audit trail
        """
        if tools is None:
            tools = []

        crew = NBACrewFactory.create_crew()

        # Inject tools (Card Store queries, etc.)
        for agent in crew.agents:
            agent.tools = tools

        # Create input prompt
        input_text = f"""
        Financial Optimization Analysis
        ================================
        Trigger Type: {trigger_type}

        Context:
        {context}

        Please analyze the situation and generate prioritized recommendations.
        """

        # Run crew (blocking call wrapped in async)
        try:
            result = await asyncio.to_thread(crew.kickoff, {"input": input_text})
            return {"status": "success", "recommendations": result}
        except Exception as e:
            logger.error(f"NBA crew execution failed: {e}")
            return {"status": "error", "error": str(e)}
