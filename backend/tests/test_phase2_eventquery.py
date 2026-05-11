"""Phase 2: EventQueryTransport tests."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.membrane.event_query import (
    EmbarkEventQuery,
    EventRecord,
    LocalEventQuery,
    QueryFilter,
    create_query_transport,
)
from backend.membrane.transport import Channel


def _ev(eid: str, **kw) -> EventRecord:
    return EventRecord(
        event_id=eid,
        channel=kw.pop("channel", Channel.IMPACT_PROPOSED_INVOICE_INGESTED),
        occurred_at=kw.pop("occurred_at", datetime.now(timezone.utc)),
        payload=kw.pop("payload", {"signal_name": "INVOICE_INGESTED"}),
        signal_id=kw.pop("signal_id", 1),
        correlation_id=kw.pop("correlation_id", None),
    )


@pytest.mark.asyncio
async def test_local_record_and_get_event() -> None:
    q = LocalEventQuery()
    await q.record(_ev("e1"))
    got = await q.get_event("e1")
    assert got is not None and got.event_id == "e1"
    assert (await q.get_event("missing")) is None


@pytest.mark.asyncio
async def test_local_query_by_channel_and_correlation() -> None:
    q = LocalEventQuery()
    await q.record(_ev("a", correlation_id="cor-1"))
    await q.record(_ev("b", channel=Channel.IMPACT_RESOLVED_JE_POSTED, correlation_id="cor-2"))
    res = await q.query(QueryFilter(channel=Channel.IMPACT_PROPOSED_INVOICE_INGESTED))
    assert {e.event_id for e in res} == {"a"}
    res2 = await q.query(QueryFilter(correlation_id="cor-2"))
    assert {e.event_id for e in res2} == {"b"}


@pytest.mark.asyncio
async def test_local_query_time_range() -> None:
    q = LocalEventQuery()
    now = datetime.now(timezone.utc)
    await q.record(_ev("old", occurred_at=now - timedelta(hours=2)))
    await q.record(_ev("new", occurred_at=now))
    res = await q.query(QueryFilter(since=now - timedelta(minutes=10)))
    assert {e.event_id for e in res} == {"new"}


@pytest.mark.asyncio
async def test_local_search_text() -> None:
    q = LocalEventQuery()
    await q.record(_ev("e1", payload={"vendor": "Acme Plumbing"}))
    await q.record(_ev("e2", payload={"vendor": "Beta Electric"}))
    res = await q.search("acme")
    assert {e.event_id for e in res} == {"e1"}


@pytest.mark.asyncio
async def test_local_health() -> None:
    q = LocalEventQuery()
    h = await q.health()
    assert h.healthy and h.backend == "local"


@pytest.mark.asyncio
async def test_platform_query_stub() -> None:
    q = EmbarkEventQuery()
    h = await q.health()
    assert h.backend == "platform" and h.healthy is False
    with pytest.raises(NotImplementedError):
        await q.query(QueryFilter())


def test_query_factory() -> None:
    assert create_query_transport("local").backend_name == "local"
    assert create_query_transport("platform").backend_name == "platform"
    with pytest.raises(ValueError):
        create_query_transport("bogus")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("REDIS_INTEGRATION") != "1",
    reason="set REDIS_INTEGRATION=1 with docker-compose redis to run",
)
async def test_redis_event_query_integration() -> None:
    from backend.membrane.event_query.redis_query import RedisEventQuery
    q = RedisEventQuery()
    ev = _ev("redis-ev-1", correlation_id="corX")
    await q.record(ev)
    got = await q.get_event("redis-ev-1")
    assert got is not None and got.correlation_id == "corX"
    res = await q.query(QueryFilter(channel=ev.channel, limit=10))
    assert any(e.event_id == "redis-ev-1" for e in res)
    s = await q.search("INVOICE_INGESTED")
    assert any(e.event_id == "redis-ev-1" for e in s)
