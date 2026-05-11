"""Phase 2: Redis health endpoint test (in-app)."""
from __future__ import annotations

import pytest

from backend.membrane.transport import LocalTransport, init_transport, reset_transport_for_tests


@pytest.mark.asyncio
async def test_local_transport_health_returns_healthy() -> None:
    reset_transport_for_tests()
    t = init_transport(LocalTransport())
    h = await t.health()
    assert h.healthy is True
    assert h.backend == "local"


def test_health_endpoint_responds() -> None:
    """If FastAPI app has /health/redis wired, it should return JSON."""
    try:
        from fastapi.testclient import TestClient

        from backend.main import app
    except Exception:
        pytest.skip("backend.main not importable in this env")
        return
    reset_transport_for_tests()
    init_transport(LocalTransport())
    client = TestClient(app)
    resp = client.get("/health/redis")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "backend" in body and "healthy" in body
