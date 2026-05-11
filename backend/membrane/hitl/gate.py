"""HITLGate — pause/resume Flow at human-decision points.

The gate is invoked by `hitl_invoice_gate` (a conversationalist skill). It:
  1. Writes the Episode Card with status=SUSPENDED and a pending_question dict.
  2. Returns a `HITLPauseInstruction` that the Flow uses to suspend execution.
  3. On resume (driven by the `/v2/hitl/{id}/decision` endpoint), verifies the
     signed DecisionToken, injects the human intent into the Episode Card, and
     flips status back to RUNNING so the Flow can re-enter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.skills.episode_card import (
    EpisodeCard,
    FileEpisodeCardStore,
)

from .decision_token import DecisionToken
from .token_signer import HITLTokenSigner, get_default_signer


@dataclass
class HITLPauseInstruction:
    """Returned by the gate when the Flow must suspend.

    The Flow's outer driver inspects `pause=True` and stops processing.
    """

    episode_id: str
    question: str
    options: list = field(default_factory=list)
    pause: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pause": True,
            "episode_id": self.episode_id,
            "question": self.question,
            "options": list(self.options),
        }


class HITLGate:
    """Coordinator between Flow, Episode Card, and signed DecisionToken."""

    def __init__(
        self,
        store: Optional[FileEpisodeCardStore] = None,
        signer: Optional[HITLTokenSigner] = None,
    ) -> None:
        self.store = store or FileEpisodeCardStore()
        self.signer = signer or get_default_signer()

    # ------------------------------------------------------------------ pause
    def request_pause(
        self,
        episode_id: str,
        question: str,
        options: Optional[list] = None,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> HITLPauseInstruction:
        """Mark the episode SUSPENDED and return a pause instruction."""
        card = self.store.read(episode_id)
        if card is None:
            # Defensive: synthesize a stub card so the gate is usable in tests
            # before any flow step has persisted state.
            now = datetime.now(tz=timezone.utc).isoformat()
            card = EpisodeCard(
                episode_id=episode_id,
                workflow="hitl",
                status="SUSPENDED",
                started_at=now,
                updated_at=now,
                inputs=dict(context or {}),
            )
        card.status = "SUSPENDED"
        card.last_output = {
            "hitl_pending": {
                "question": question,
                "options": list(options or []),
                "asked_at": datetime.now(tz=timezone.utc).isoformat(),
                "context": dict(context or {}),
            }
        }
        self.store.write(card)
        return HITLPauseInstruction(
            episode_id=episode_id, question=question, options=list(options or [])
        )

    # ----------------------------------------------------------------- sign
    def sign_decision(
        self,
        *,
        episode_id: str,
        principal: str,
        decision: str,
        reasoning: str = "",
        timestamp: Optional[str] = None,
    ) -> DecisionToken:
        ts = timestamp or datetime.now(tz=timezone.utc).isoformat()
        return self.signer.sign(
            {
                "episode_id": episode_id,
                "principal": principal,
                "decision": decision,
                "reasoning": reasoning,
                "timestamp": ts,
            }
        )

    # ---------------------------------------------------------------- resume
    def resume(self, token: DecisionToken) -> EpisodeCard:
        """Verify token + inject decision into the Episode Card.

        Raises whatever HITLTokenSigner.verify raises, plus KeyError if the
        episode doesn't exist, or ValueError on episode_id mismatch / not
        currently suspended.
        """
        verified = self.signer.verify(token)
        card = self.store.read(verified.episode_id)
        if card is None:
            raise KeyError(f"episode {verified.episode_id!r} not found")
        if card.status != "SUSPENDED":
            raise ValueError(
                f"episode {verified.episode_id!r} is not suspended (status={card.status})"
            )

        # Inject the human intent. Keep pending question for audit but stamp
        # the resolution into `inputs.human_decision` so the Flow's next step
        # can read it deterministically.
        card.inputs["human_decision"] = {
            "principal": verified.principal,
            "decision": verified.decision,
            "reasoning": verified.reasoning,
            "timestamp": verified.timestamp,
            "key_id": verified.key_id,
        }
        card.last_output = {
            **card.last_output,
            "hitl_resolution": {
                "decision": verified.decision,
                "principal": verified.principal,
                "resolved_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        }
        card.status = "RUNNING"
        self.store.write(card)
        return card


__all__ = ["HITLGate", "HITLPauseInstruction"]
