"""DecisionToken — frozen Pydantic model for signed HITL decisions."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DecisionLiteral = Literal["APPROVE", "REJECT", "ESCALATE"]


class DecisionToken(BaseModel):
    """Immutable HITL decision payload + RSA signature envelope.

    The `signature` covers a canonical JSON encoding of all other fields
    EXCEPT `signature` itself. `key_id` identifies which signing key was used
    so the verifier can support rotation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_id: str = Field(..., min_length=1)
    principal: str = Field(..., min_length=1)
    decision: DecisionLiteral
    reasoning: str = ""
    timestamp: str = Field(..., min_length=1)
    signature: str = Field(..., min_length=1)
    key_id: str = Field(..., min_length=1)

    def signed_payload(self) -> dict:
        """Return the dict that the signature covers (everything but the sig)."""
        return {
            "episode_id": self.episode_id,
            "principal": self.principal,
            "decision": self.decision,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp,
            "key_id": self.key_id,
        }


__all__ = ["DecisionToken", "DecisionLiteral"]
