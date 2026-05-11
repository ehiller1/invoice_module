"""Phase 6: HITL token signing/verification tests."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.membrane.hitl import (
    DecisionToken,
    HITLTokenSigner,
    InvalidSignatureError,
    TokenExpiredError,
    UnknownKeyError,
)


@pytest.fixture
def signer() -> HITLTokenSigner:
    return HITLTokenSigner(ttl_seconds=3600, max_keys=10)


def _make_payload(episode_id: str = "ep-1") -> dict:
    return {
        "episode_id": episode_id,
        "principal": "treasurer@church.example",
        "decision": "APPROVE",
        "reasoning": "looks fine",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def test_sign_returns_token_with_signature(signer: HITLTokenSigner) -> None:
    tok = signer.sign(_make_payload())
    assert tok.signature
    assert tok.key_id
    assert tok.episode_id == "ep-1"


def test_verify_round_trip(signer: HITLTokenSigner) -> None:
    tok = signer.sign(_make_payload())
    verified = signer.verify(tok)
    assert verified.decision == "APPROVE"
    assert verified.principal == "treasurer@church.example"


def test_verify_detects_tampering_decision(signer: HITLTokenSigner) -> None:
    tok = signer.sign(_make_payload())
    tampered = tok.model_copy(update={"decision": "REJECT"})
    with pytest.raises(InvalidSignatureError):
        signer.verify(tampered)


def test_verify_detects_tampering_principal(signer: HITLTokenSigner) -> None:
    tok = signer.sign(_make_payload())
    tampered = tok.model_copy(update={"principal": "attacker@evil.example"})
    with pytest.raises(InvalidSignatureError):
        signer.verify(tampered)


def test_verify_detects_signature_corruption(signer: HITLTokenSigner) -> None:
    tok = signer.sign(_make_payload())
    bad_sig = tok.model_copy(update={"signature": "AAAA" + tok.signature[4:]})
    with pytest.raises(InvalidSignatureError):
        signer.verify(bad_sig)


def test_key_rotation_old_token_still_verifies(signer: HITLTokenSigner) -> None:
    tok_old = signer.sign(_make_payload())
    signer.rotate_key()
    tok_new = signer.sign(_make_payload(episode_id="ep-2"))
    assert tok_old.key_id != tok_new.key_id
    # Both must still verify.
    assert signer.verify(tok_old).episode_id == "ep-1"
    assert signer.verify(tok_new).episode_id == "ep-2"


def test_key_rotation_evicts_beyond_max_keys() -> None:
    s = HITLTokenSigner(ttl_seconds=3600, max_keys=3)
    tok_first = s.sign(_make_payload())
    # rotate enough times to evict the original key
    for _ in range(3):
        s.rotate_key()
    with pytest.raises(UnknownKeyError):
        s.verify(tok_first)


def test_expired_token_rejected() -> None:
    s = HITLTokenSigner(ttl_seconds=1)
    tok = s.sign(_make_payload())
    time.sleep(1.2)
    with pytest.raises(TokenExpiredError):
        s.verify(tok)


def test_future_timestamp_outside_skew_rejected(signer: HITLTokenSigner) -> None:
    p = _make_payload()
    p["timestamp"] = (datetime.now(tz=timezone.utc) + timedelta(hours=2)).isoformat()
    tok = signer.sign(p)
    # We deliberately accept clock skew up to a small window but reject 2h ahead.
    with pytest.raises(TokenExpiredError):
        signer.verify(tok)


def test_decision_token_frozen() -> None:
    p = _make_payload()
    tok = DecisionToken(
        episode_id=p["episode_id"],
        principal=p["principal"],
        decision=p["decision"],
        reasoning=p["reasoning"],
        timestamp=p["timestamp"],
        signature="sig",
        key_id="k1",
    )
    with pytest.raises(Exception):
        tok.decision = "REJECT"  # type: ignore[misc]


def test_decision_validates_enum() -> None:
    with pytest.raises(Exception):
        DecisionToken(
            episode_id="e",
            principal="p",
            decision="MAYBE",  # invalid
            reasoning="",
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            signature="s",
            key_id="k",
        )
