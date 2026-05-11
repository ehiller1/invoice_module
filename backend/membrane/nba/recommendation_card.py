"""Phase 13: Recommendation Card Schema.

Represents actionable financial recommendations from the NBA crew.
Includes confidence scores, projected impact, and risk assessment.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class RecommendationPriority(str, Enum):
    """Priority level for recommendations."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationStatus(str, Enum):
    """Status of a recommendation."""
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    DEFERRED = "deferred"
    EXECUTED = "executed"


class RecommendationCard(BaseModel):
    """Recommendation Card from NBA crew.

    Represents a single actionable financial recommendation with:
    - Projected impact (GL cells affected, amounts)
    - Confidence score and risk assessment
    - Alternative recommendations
    - Decision audit trail
    """
    card_id: str = Field(..., description="Unique recommendation ID")
    principal: str = Field(default="nba-crew", description="Authoring principal (always NBA crew)")
    created_at: datetime = Field(..., description="When recommendation was generated")
    updated_at: datetime = Field(..., description="When recommendation was last updated")

    # Recommendation content
    recommendation_id: str = Field(..., description="Unique ID for this recommendation")
    title: str = Field(..., description="Short title of recommendation")
    description: str = Field(..., description="Detailed description of what to do")

    # Trigger context
    trigger_type: str = Field(..., description="What triggered this: budget_overage, exception, policy_violation, etc.")
    trigger_ids: List[str] = Field(default_factory=list, description="IDs of triggering events/signals")

    # Impact & metrics
    projected_impact: Dict[str, Decimal] = Field(
        default_factory=dict,
        description="Projected GL impact: {gl_account: amount}"
    )
    affected_accounts: List[str] = Field(default_factory=list, description="GL accounts affected")
    affected_dimensions: Dict[str, str] = Field(
        default_factory=dict,
        description="Affected dimensions: {dimension_name: dimension_value}"
    )

    # Confidence & risk
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0-1.0)"
    )
    priority: RecommendationPriority = Field(..., description="Priority level")
    risk_level: str = Field(..., description="Risk level: low, medium, high, critical")
    risk_factors: List[str] = Field(default_factory=list, description="Identified risk factors")

    # Alternatives & reasoning
    reasoning: str = Field(..., description="Why this recommendation is suggested")
    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Alternative recommendations with confidence/risk"
    )
    prerequisites: List[str] = Field(
        default_factory=list,
        description="Prerequisites to executing this recommendation"
    )

    # Decision tracking
    status: RecommendationStatus = Field(default=RecommendationStatus.PROPOSED)
    decided_at: Optional[datetime] = Field(default=None, description="When decision was made")
    decided_by: Optional[str] = Field(default=None, description="Who made the decision")
    decision_notes: Optional[str] = Field(default=None, description="Notes on the decision")

    # Audit trail
    approval_chain: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Decision approval chain with timestamps"
    )

    class Config:
        """Pydantic config."""
        json_schema_extra = {
            "example": {
                "card_id": "rec-2026-05-11-001",
                "principal": "nba-crew",
                "recommendation_id": "rec-budget-overage-41000",
                "title": "Reduce GL 41000 allocation",
                "description": "GL account 41000 is at 95% budget. Recommend reducing non-essential spending.",
                "trigger_type": "budget_overage",
                "trigger_ids": ["signal-budget-overage-41000"],
                "projected_impact": {"41000": Decimal("-5000")},
                "affected_accounts": ["41000"],
                "confidence": 0.85,
                "priority": "high",
                "risk_level": "low",
                "risk_factors": ["minimal disruption", "reversible if needed"],
                "reasoning": "Current burn rate suggests overage by month end without action",
                "status": "proposed",
            }
        }
