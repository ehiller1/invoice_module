"""Phase 4 — Verdict schema tests."""
from __future__ import annotations

import pytest

from backend.membrane.guiders.base import Decision, Verdict


def test_verdict_basic_fields():
    v = Verdict(
        guider="accounting-integrity",
        decision=Decision.APPROVE,
        confidence=0.9,
        reason="ok",
    )
    assert v.guider == "accounting-integrity"
    assert v.decision == Decision.APPROVE
    assert v.confidence == 0.9
    assert v.override_allowed_by == []
    assert v.metadata == {}


def test_verdict_confidence_out_of_range():
    with pytest.raises(ValueError):
        Verdict(guider="x", decision=Decision.APPROVE, confidence=1.5, reason="r")
    with pytest.raises(ValueError):
        Verdict(guider="x", decision=Decision.APPROVE, confidence=-0.1, reason="r")


def test_verdict_decision_must_be_enum():
    with pytest.raises(TypeError):
        Verdict(guider="x", decision="APPROVE", confidence=0.5, reason="r")  # type: ignore


def test_override_allowed_requires_principals():
    with pytest.raises(ValueError):
        Verdict(
            guider="x",
            decision=Decision.OVERRIDE_ALLOWED,
            confidence=0.9,
            reason="r",
        )


def test_override_allowed_with_principals_ok():
    v = Verdict(
        guider="polity",
        decision=Decision.OVERRIDE_ALLOWED,
        confidence=0.9,
        reason="needs treasurer",
        override_allowed_by=["TREASURER", "ADMIN"],
    )
    assert v.can_override(["TREASURER"])
    assert v.can_override(["ADMIN"])
    assert not v.can_override(["FINANCE_STAFF"])
    assert not v.can_override([])


def test_is_blocking_and_hard_block():
    block = Verdict("x", Decision.BLOCK, 1.0, "r")
    over = Verdict("x", Decision.OVERRIDE_ALLOWED, 1.0, "r", override_allowed_by=["ADMIN"])
    appr = Verdict("x", Decision.APPROVE, 1.0, "r")

    assert block.is_hard_block
    assert block.is_blocking
    assert not over.is_hard_block
    assert over.is_blocking
    assert not appr.is_blocking


def test_approve_verdict_cannot_be_overridden():
    v = Verdict("x", Decision.APPROVE, 1.0, "r")
    assert not v.can_override(["TREASURER"])
