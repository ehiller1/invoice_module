"""Phase 15: Scenario Card Schema.

What-if simulator for GL projections.
Stores temporary scenario GL states with assumptions and impact analysis.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class ScenarioType(str, Enum):
    """Scenario types for what-if analysis."""
    BASELINE = "baseline"
    OPTIMISTIC = "optimistic"
    PESSIMISTIC = "pessimistic"
    CUSTOM = "custom"


class ScenarioStatus(str, Enum):
    """Status of a scenario projection."""
    DRAFT = "draft"
    APPROVED = "approved"
    EXECUTED = "executed"
    ARCHIVED = "archived"


class ScenarioCard(BaseModel):
    """Scenario Card for what-if analysis.

    Represents a temporary GL projection with specific assumptions.
    Used to simulate impact of proposed changes.
    """
    card_id: str = Field(..., description="Unique scenario ID")
    principal: str = Field(default="scenario-engine", description="Author (always scenario-engine)")
    created_at: datetime = Field(..., description="When scenario was created")
    updated_at: datetime = Field(..., description="When scenario was last updated")

    # Scenario definition
    scenario_id: str = Field(..., description="Unique scenario identifier")
    name: str = Field(..., description="Human-readable scenario name")
    description: str = Field(..., description="What-if scenario description")
    scenario_type: ScenarioType = Field(..., description="Scenario type")

    # GL impact
    base_gl: Dict[str, Decimal] = Field(..., description="Starting GL state")
    projected_gl: Dict[str, Decimal] = Field(..., description="Projected GL after changes")
    changes: Dict[str, Decimal] = Field(
        default_factory=dict,
        description="GL changes: {account: delta}"
    )

    # Assumptions
    assumptions: Dict[str, Any] = Field(
        default_factory=dict,
        description="Assumptions underlying the projection"
    )
    key_drivers: Dict[str, str] = Field(
        default_factory=dict,
        description="Key drivers of changes"
    )

    # Impact analysis
    impact_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of impact (variance %, affected accounts, etc.)"
    )
    affected_dimensions: Dict[str, str] = Field(
        default_factory=dict,
        description="Affected cost centers, funds, restrictions"
    )

    # Constraints & risks
    budget_impact: Decimal = Field(
        default=Decimal("0"),
        description="Total budget variance from projection"
    )
    policy_violations: list[str] = Field(
        default_factory=list,
        description="Any policy violations identified"
    )
    risk_level: str = Field(default="low", description="Risk: low, medium, high")

    # Status & decision
    status: ScenarioStatus = Field(default=ScenarioStatus.DRAFT)
    approved_at: Optional[datetime] = Field(default=None)
    approved_by: Optional[str] = Field(default=None)
    execution_date: Optional[datetime] = Field(default=None)

    class Config:
        """Pydantic config."""
        json_schema_extra = {
            "example": {
                "card_id": "scenario-2026-05-11-001",
                "scenario_id": "scenario-reduce-41000",
                "name": "Reduce GL 41000 allocation",
                "description": "What if we reduce non-essential spending by 10%?",
                "scenario_type": "custom",
                "base_gl": {"41000": Decimal("10000")},
                "projected_gl": {"41000": Decimal("9000")},
                "changes": {"41000": Decimal("-1000")},
            }
        }
