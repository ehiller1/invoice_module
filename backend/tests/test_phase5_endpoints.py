"""Phase 5 endpoint tests — queue action endpoints + intents/answer."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_card_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("EMBARK_CARD_JSONL_DIR", str(tmp_path))
    # Reload stores so they pick up the new dir.
    import importlib
    from backend.tools import exception_store, question_store, policy_store
    importlib.reload(exception_store)
    importlib.reload(question_store)
    importlib.reload(policy_store)
    yield


@pytest.fixture
def client():
    app = FastAPI()
    from backend.routes import exceptions, questions, policies, reconciliation
    app.include_router(exceptions.router)
    app.include_router(questions.router)
    app.include_router(policies.router)
    app.include_router(reconciliation.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Exceptions Queue
# ---------------------------------------------------------------------------

def test_exception_resolve(client):
    from backend.tools import exception_store
    rec = exception_store.create_exception("c1", title="T", description="D")
    r = client.post(f"/api/exceptions/{rec['card_id']}/resolve?church_id=c1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "RESOLVED"


def test_exception_approve_writes_decision(client):
    from backend.tools import exception_store
    rec = exception_store.create_exception("c1", title="T", description="D")
    r = client.post(
        f"/api/exceptions/{rec['card_id']}/approve",
        params={"church_id": "c1"},
        json={"actor": "alice", "reasoning": "ok"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "APPROVED"
    assert body["packet"]["actor"] == "alice"


def test_exception_reject_writes_decision(client):
    from backend.tools import exception_store
    rec = exception_store.create_exception("c1", title="T", description="D")
    r = client.post(
        f"/api/exceptions/{rec['card_id']}/reject",
        params={"church_id": "c1"},
        json={"actor": "bob", "reasoning": "nope"},
    )
    assert r.status_code == 200
    assert r.json()["verdict"] == "REJECTED"


def test_exception_route_updates_principal(client, monkeypatch):
    monkeypatch.setenv("EMBARK_MEMBRANE_PHASE_5", "1")
    from backend.tools import exception_store
    rec = exception_store.create_exception(
        "c1", title="T", description="D", principal="alice"
    )
    r = client.post(
        f"/api/exceptions/{rec['card_id']}/route",
        params={"church_id": "c1"},
        json={"principal": "bob", "actor": "alice", "reason": "needs treasurer"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["principal"] == "bob"


def test_exception_route_requires_principal(client):
    r = client.post(
        "/api/exceptions/exc-x/route",
        params={"church_id": "c1"},
        json={"actor": "alice"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Questions Queue
# ---------------------------------------------------------------------------

def test_question_answer_human(client):
    from backend.tools import question_store
    q = question_store.create_question("c1", query="why?", intent="explain")
    r = client.post(
        f"/api/churches/c1/questions/{q['question_id']}/answer",
        json={"answer": "because policy", "answerer": "alice"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] is False
    assert body["answer_record"]["answers"][-1]["answer"] == "because policy"


def test_question_answer_cascade_when_no_answer(client):
    from backend.tools import question_store
    q = question_store.create_question("c1", query="how much budget left?")
    r = client.post(
        f"/api/churches/c1/questions/{q['question_id']}/answer",
        json={},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] is True
    assert body["answer_record"]["answers"][-1]["source"] in ("cascade", "fallback")


# ---------------------------------------------------------------------------
# Policies Queue
# ---------------------------------------------------------------------------

def test_policy_vote_records_tally(client):
    from backend.tools import policy_store
    p = policy_store.create_policy("c1", title="P", description="D", quorum=2)
    r = client.post(
        f"/api/policies/{p['policy_id']}/vote",
        params={"church_id": "c1"},
        json={"voter_id": "v1", "value": "YES"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tally"]["yes"] == 1


def test_policy_vote_quorum_passes(client):
    from backend.tools import policy_store
    p = policy_store.create_policy("c1", title="P", description="D", quorum=2)
    pid = p["policy_id"]
    client.post(f"/api/policies/{pid}/vote", params={"church_id": "c1"},
                json={"voter_id": "v1", "value": "YES"})
    r = client.post(f"/api/policies/{pid}/vote", params={"church_id": "c1"},
                    json={"voter_id": "v2", "value": "YES"})
    body = r.json()
    assert body["status"] == "PASSED"
    assert body["quorum"]["reached"] is True


def test_policy_vote_invalid_value(client):
    from backend.tools import policy_store
    p = policy_store.create_policy("c1", title="P", description="D")
    r = client.post(
        f"/api/policies/{p['policy_id']}/vote",
        params={"church_id": "c1"},
        json={"voter_id": "v1", "value": "MAYBE"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Reconciliation latest
# ---------------------------------------------------------------------------

def test_reconciliation_latest_empty(client):
    r = client.get("/api/churches/c1/reconciliations/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False


def test_reconciliation_latest_returns_record(client, tmp_path, monkeypatch):
    # Write a synthetic recon record.
    import json
    cards_dir = Path(os.environ["EMBARK_CARD_JSONL_DIR"])
    p = cards_dir / "reconciliations_c1.jsonl"
    p.write_text(json.dumps({
        "run_id": "r1",
        "completed_at": "2026-05-11T10:00:00",
        "matched_count": 5,
        "unmatched_count": 2,
        "exception_count": 1,
    }) + "\n")
    r = client.get("/api/churches/c1/reconciliations/latest")
    body = r.json()
    assert body["found"] is True
    assert body["summary"]["matched_count"] == 5
    assert body["summary"]["run_id"] == "r1"


# ---------------------------------------------------------------------------
# Store-level: dual-write JSONL fallback
# ---------------------------------------------------------------------------

def test_exception_store_persists_to_jsonl():
    from backend.tools import exception_store
    rec = exception_store.create_exception("c2", title="A", description="B")
    fetched = exception_store.get_exception("c2", rec["card_id"])
    assert fetched is not None
    assert fetched["status"] == "OPEN"


def test_policy_store_tracks_votes_idempotently():
    from backend.tools import policy_store
    p = policy_store.create_policy("c2", title="P", description="D", quorum=3)
    policy_store.record_vote("c2", p["policy_id"], voter_id="v1", value="YES")
    policy_store.record_vote("c2", p["policy_id"], voter_id="v1", value="NO")  # change vote
    rec = policy_store.get_policy("c2", p["policy_id"])
    assert rec["tally"]["yes"] == 0
    assert rec["tally"]["no"] == 1
