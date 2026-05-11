"""Phase 6: HITLGate pause/resume tests."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.membrane.hitl import (
    HITLGate,
    HITLTokenSigner,
    InvalidSignatureError,
)
from backend.skills.episode_card import (
    EpisodeCard,
    FileEpisodeCardStore,
    new_episode,
)


@pytest.fixture
def store(tmp_path: Path) -> FileEpisodeCardStore:
    return FileEpisodeCardStore(root=tmp_path / "episodes")


@pytest.fixture
def gate(store: FileEpisodeCardStore) -> HITLGate:
    return HITLGate(store=store, signer=HITLTokenSigner(ttl_seconds=600))


def test_request_pause_marks_suspended_and_returns_instruction(
    gate: HITLGate, store: FileEpisodeCardStore
) -> None:
    card = new_episode("invoice_processing", {"invoice_id": "INV-1"})
    store.write(card)

    instr = gate.request_pause(
        card.episode_id,
        "Approve this invoice?",
        options=["APPROVE", "REJECT"],
        context={"vendor": "Acme"},
    )

    assert instr.pause is True
    assert instr.episode_id == card.episode_id
    assert instr.question == "Approve this invoice?"

    reloaded = store.read(card.episode_id)
    assert reloaded is not None
    assert reloaded.status == "SUSPENDED"
    assert reloaded.last_output["hitl_pending"]["question"] == "Approve this invoice?"
    assert reloaded.last_output["hitl_pending"]["context"]["vendor"] == "Acme"


def test_request_pause_creates_stub_when_missing(gate: HITLGate, store: FileEpisodeCardStore) -> None:
    instr = gate.request_pause("never-seen", "Q?", options=["A"])
    assert instr.pause is True
    card = store.read("never-seen")
    assert card is not None and card.status == "SUSPENDED"


def test_resume_round_trip_injects_intent(gate: HITLGate, store: FileEpisodeCardStore) -> None:
    card = new_episode("invoice_processing", {"invoice_id": "INV-2"})
    store.write(card)
    gate.request_pause(card.episode_id, "Approve?", options=["APPROVE", "REJECT"])

    tok = gate.sign_decision(
        episode_id=card.episode_id,
        principal="treasurer@church.example",
        decision="APPROVE",
        reasoning="vendor verified",
    )

    resumed = gate.resume(tok)
    assert resumed.status == "RUNNING"
    assert resumed.inputs["human_decision"]["decision"] == "APPROVE"
    assert resumed.inputs["human_decision"]["principal"] == "treasurer@church.example"
    assert resumed.last_output["hitl_resolution"]["decision"] == "APPROVE"

    # And persisted.
    reloaded = store.read(card.episode_id)
    assert reloaded is not None
    assert reloaded.status == "RUNNING"
    assert reloaded.inputs["human_decision"]["reasoning"] == "vendor verified"


def test_resume_rejects_tampered_token(gate: HITLGate, store: FileEpisodeCardStore) -> None:
    card = new_episode("wf", {})
    store.write(card)
    gate.request_pause(card.episode_id, "Q?")
    tok = gate.sign_decision(
        episode_id=card.episode_id, principal="user", decision="APPROVE"
    )
    tampered = tok.model_copy(update={"decision": "REJECT"})
    with pytest.raises(InvalidSignatureError):
        gate.resume(tampered)


def test_resume_fails_if_not_suspended(gate: HITLGate, store: FileEpisodeCardStore) -> None:
    card = new_episode("wf", {})
    store.write(card)  # status=RUNNING
    tok = gate.sign_decision(
        episode_id=card.episode_id, principal="user", decision="APPROVE"
    )
    with pytest.raises(ValueError):
        gate.resume(tok)


def test_resume_fails_if_episode_missing(gate: HITLGate) -> None:
    tok = gate.sign_decision(
        episode_id="does-not-exist", principal="user", decision="APPROVE"
    )
    with pytest.raises(KeyError):
        gate.resume(tok)


def test_decision_options_validated() -> None:
    # ESCALATE is allowed.
    g = HITLGate(signer=HITLTokenSigner())
    tok = g.sign_decision(episode_id="e", principal="p", decision="ESCALATE")
    assert tok.decision == "ESCALATE"
