"""Tests for policy vote storage + quorum promotion.

Covers the round-2 fixes:
  * Votes are indexed by policy_id in the policy_votes table.
  * (policy_id, voter_id) is unique — re-voting upserts rather than duplicating.
  * The third yes vote across distinct voters flips the policy_card to RESOLVED.
"""
from __future__ import annotations

import asyncio
import os
import uuid
import pytest

# Tests in this module hit Postgres. Skip cleanly when no DB is reachable so
# `pytest` on a dev box without docker doesn't fail with a connection error.
try:
    from backend.db.connection import execute_query
    execute_query("SELECT 1", fetch_one=True)
    _DB_OK = True
except Exception:  # pragma: no cover - environment-dependent
    _DB_OK = False

pytestmark = pytest.mark.skipif(not _DB_OK, reason="Postgres not reachable in this environment")


CHURCH = os.environ.get("EMBARK_DEFAULT_CHURCH", "holy_comforter")


def _new_policy_id(prefix: str = "test-pol") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _seed_policy_card(policy_id: str, title: str = "Test policy") -> str:
    from backend.db import card_store
    return card_store.create_policy_card(
        church_id=CHURCH,
        policy_id=policy_id,
        title=title,
        description="Created by test",
        requires_vote=True,
    )


@pytest.fixture(autouse=True)
def _cleanup_after():
    """Remove any test-* rows after each test so re-runs stay deterministic."""
    yield
    try:
        execute_query("DELETE FROM policy_votes WHERE policy_id LIKE %s", ("test-pol-%",))
        execute_query("DELETE FROM policy_cards WHERE policy_id LIKE %s", ("test-pol-%",))
    except Exception:
        pass


class TestPolicyVoteStorage:
    def test_record_vote_inserts_row(self):
        from backend.db import policy_votes_store
        pid = _new_policy_id()
        rec = policy_votes_store.record_vote(
            pid, "treasurer-1", "yes",
            church_id=CHURCH, voter_role="TREASURER", rationale="LGTM",
        )
        assert rec["policy_id"] == pid
        assert rec["voter_id"] == "treasurer-1"
        assert rec["vote"] == "yes"
        assert rec["rationale"] == "LGTM"

    def test_revote_upserts_same_row(self):
        from backend.db import policy_votes_store
        pid = _new_policy_id()
        policy_votes_store.record_vote(pid, "voter-1", "yes", church_id=CHURCH)
        policy_votes_store.record_vote(pid, "voter-1", "no",  church_id=CHURCH)
        votes = policy_votes_store.votes_for_policies([pid])[pid]
        assert len(votes) == 1
        assert votes[0]["vote"] == "no"

    def test_tally_aggregates_by_vote(self):
        from backend.db import policy_votes_store
        pid = _new_policy_id()
        policy_votes_store.record_vote(pid, "a", "yes",     church_id=CHURCH)
        policy_votes_store.record_vote(pid, "b", "yes",     church_id=CHURCH)
        policy_votes_store.record_vote(pid, "c", "no",      church_id=CHURCH)
        policy_votes_store.record_vote(pid, "d", "abstain", church_id=CHURCH)
        t = policy_votes_store.tally(pid)
        assert t == {"yes": 2, "no": 1, "abstain": 1, "total": 4}

    def test_votes_for_policies_one_query(self):
        from backend.db import policy_votes_store
        pid1, pid2 = _new_policy_id(), _new_policy_id()
        policy_votes_store.record_vote(pid1, "a", "yes", church_id=CHURCH)
        policy_votes_store.record_vote(pid2, "b", "yes", church_id=CHURCH)
        out = policy_votes_store.votes_for_policies([pid1, pid2])
        assert set(out.keys()) == {pid1, pid2}
        assert len(out[pid1]) == 1
        assert len(out[pid2]) == 1


class TestQuorumPromotion:
    """The vote_on_policy route should flip the card to RESOLVED when quorum hits."""

    def test_promotes_to_resolved_on_third_yes(self):
        from backend.routes import policies as routes_policies
        from backend.db.connection import execute_query

        pid = _new_policy_id("test-pol-promote")
        _seed_policy_card(pid, title="Promotion test")

        async def _go():
            # First two yes votes — still OPEN.
            r1 = await routes_policies.vote_on_policy(
                policy_id=pid, body={"vote": "yes"}, church_id=None,
                x_voter_id="treasurer-1", x_user_role="TREASURER", x_church_id=CHURCH,
            )
            r2 = await routes_policies.vote_on_policy(
                policy_id=pid, body={"vote": "yes"}, church_id=None,
                x_voter_id="finance-chair-1", x_user_role="FINANCE_CHAIR", x_church_id=CHURCH,
            )
            assert r1.get("activated") is False
            assert r2.get("activated") is False

            # Third yes vote — quorum (default 3) reached.
            r3 = await routes_policies.vote_on_policy(
                policy_id=pid, body={"vote": "yes"}, church_id=None,
                x_voter_id="vestry-senior-1", x_user_role="VESTRY_SENIOR", x_church_id=CHURCH,
            )
            assert r3.get("activated") is True

        asyncio.run(_go())

        row = execute_query(
            "SELECT status, resolution_data FROM policy_cards WHERE policy_id=%s",
            (pid,), fetch_one=True,
        )
        assert row is not None
        # Card_status enum doesn't include 'ACTIVE' — RESOLVED is the canonical
        # post-promotion state, with resolution_data.decision='approved'.
        assert (row.get("status") or "").upper() == "RESOLVED"
        # resolution_data may be jsonb dict or str depending on driver.
        rd = row.get("resolution_data") or {}
        if isinstance(rd, str):
            import json as _json
            rd = _json.loads(rd)
        assert rd.get("decision") == "approved"

    def test_same_voter_three_times_does_not_promote(self):
        """One voter can't reach quorum by themselves — the UNIQUE constraint makes it a no-op."""
        from backend.routes import policies as routes_policies
        from backend.db.connection import execute_query

        pid = _new_policy_id("test-pol-solo")
        _seed_policy_card(pid, title="Solo voter test")

        async def _go():
            for _ in range(3):
                await routes_policies.vote_on_policy(
                    policy_id=pid, body={"vote": "yes"}, church_id=None,
                    x_voter_id="treasurer-1", x_user_role="TREASURER", x_church_id=CHURCH,
                )

        asyncio.run(_go())

        row = execute_query(
            "SELECT status FROM policy_cards WHERE policy_id=%s",
            (pid,), fetch_one=True,
        )
        assert row is not None
        assert (row.get("status") or "").upper() == "OPEN"

    def test_guest_voter_blocked(self):
        from backend.routes import policies as routes_policies
        from fastapi import HTTPException

        pid = _new_policy_id("test-pol-guest")
        _seed_policy_card(pid, title="Guest blocked test")

        async def _go():
            try:
                await routes_policies.vote_on_policy(
                    policy_id=pid, body={"vote": "yes"}, church_id=None,
                    x_voter_id="guest", x_church_id=CHURCH,
                )
                assert False, "expected HTTPException"
            except HTTPException as e:
                assert e.status_code == 401

        asyncio.run(_go())
