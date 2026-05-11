"""Phase 6: /v2/hitl/{episode_id}/decision endpoint tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.membrane.hitl import HITLGate, HITLTokenSigner
from backend.routes import hitl as hitl_routes
from backend.skills.episode_card import FileEpisodeCardStore, new_episode


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    store = FileEpisodeCardStore(root=tmp_path / "episodes")
    gate = HITLGate(store=store, signer=HITLTokenSigner(ttl_seconds=600))
    hitl_routes.set_gate_for_tests(gate)
    a = FastAPI()
    a.include_router(hitl_routes.router)
    yield a
    hitl_routes.set_gate_for_tests(None)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _setup_suspended_episode(gate: HITLGate, *, workflow: str = "wf") -> str:
    card = new_episode(workflow, {"x": 1})
    gate.store.write(card)
    gate.request_pause(card.episode_id, "Approve?", options=["APPROVE", "REJECT"])
    return card.episode_id


def test_post_decision_resumes_flow(client: TestClient) -> None:
    gate = hitl_routes.get_gate()
    ep = _setup_suspended_episode(gate)
    tok = gate.sign_decision(
        episode_id=ep, principal="treasurer@x", decision="APPROVE", reasoning="ok"
    )
    resp = client.post(f"/v2/hitl/{ep}/decision", json={"token": tok.model_dump()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "RUNNING"
    assert body["decision"] == "APPROVE"
    assert body["resumed"] is True

    card = gate.store.read(ep)
    assert card is not None
    assert card.status == "RUNNING"
    assert card.inputs["human_decision"]["decision"] == "APPROVE"


def test_post_decision_path_token_mismatch_400(client: TestClient) -> None:
    gate = hitl_routes.get_gate()
    ep = _setup_suspended_episode(gate)
    tok = gate.sign_decision(episode_id=ep, principal="u", decision="APPROVE")
    resp = client.post(f"/v2/hitl/other-id/decision", json={"token": tok.model_dump()})
    assert resp.status_code == 400


def test_post_decision_tampered_token_401(client: TestClient) -> None:
    gate = hitl_routes.get_gate()
    ep = _setup_suspended_episode(gate)
    tok = gate.sign_decision(episode_id=ep, principal="u", decision="APPROVE")
    tampered = tok.model_copy(update={"decision": "REJECT"}).model_dump()
    resp = client.post(f"/v2/hitl/{ep}/decision", json={"token": tampered})
    assert resp.status_code == 401


def test_post_decision_unknown_episode_404(client: TestClient) -> None:
    gate = hitl_routes.get_gate()
    tok = gate.sign_decision(
        episode_id="ghost", principal="u", decision="APPROVE"
    )
    resp = client.post(f"/v2/hitl/ghost/decision", json={"token": tok.model_dump()})
    assert resp.status_code == 404


def test_post_decision_not_suspended_409(client: TestClient) -> None:
    gate = hitl_routes.get_gate()
    # write a RUNNING card with no pause
    card = new_episode("wf", {})
    gate.store.write(card)
    tok = gate.sign_decision(
        episode_id=card.episode_id, principal="u", decision="APPROVE"
    )
    resp = client.post(
        f"/v2/hitl/{card.episode_id}/decision", json={"token": tok.model_dump()}
    )
    assert resp.status_code == 409


def test_post_decision_expired_token_401(tmp_path: Path) -> None:
    import time
    store = FileEpisodeCardStore(root=tmp_path / "ep")
    gate = HITLGate(store=store, signer=HITLTokenSigner(ttl_seconds=1))
    hitl_routes.set_gate_for_tests(gate)
    try:
        ep = _setup_suspended_episode(gate)
        tok = gate.sign_decision(episode_id=ep, principal="u", decision="APPROVE")
        time.sleep(1.2)
        a = FastAPI()
        a.include_router(hitl_routes.router)
        c = TestClient(a)
        resp = c.post(f"/v2/hitl/{ep}/decision", json={"token": tok.model_dump()})
        assert resp.status_code == 401
    finally:
        hitl_routes.set_gate_for_tests(None)


def test_get_pending_returns_question(client: TestClient) -> None:
    gate = hitl_routes.get_gate()
    ep = _setup_suspended_episode(gate)
    resp = client.get(f"/v2/hitl/{ep}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUSPENDED"
    assert body["pending"]["question"] == "Approve?"


def test_get_pending_404(client: TestClient) -> None:
    resp = client.get("/v2/hitl/nope")
    assert resp.status_code == 404


def test_full_round_trip_via_endpoint_then_get(client: TestClient) -> None:
    gate = hitl_routes.get_gate()
    ep = _setup_suspended_episode(gate)
    tok = gate.sign_decision(
        episode_id=ep, principal="alice", decision="ESCALATE", reasoning="needs cmte"
    )
    r1 = client.post(f"/v2/hitl/{ep}/decision", json={"token": tok.model_dump()})
    assert r1.status_code == 200
    r2 = client.get(f"/v2/hitl/{ep}")
    body = r2.json()
    assert body["status"] == "RUNNING"
    assert body["resolution"]["decision"] == "ESCALATE"
    assert body["resolution"]["principal"] == "alice"
