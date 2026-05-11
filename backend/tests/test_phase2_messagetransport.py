"""Phase 2: MessageTransport round-trip, dead-letter, idempotency."""
from __future__ import annotations

import asyncio
import os

import pytest

from backend.membrane.transport import (
    Channel,
    Consumer,
    LocalTransport,
    PlatformTransport,
    Publisher,
    create_transport,
)
from backend.membrane.transport.base import ReceivedMessage
from backend.membrane.transport.channels import (
    ALL_CHANNELS,
    ALL_STREAM_CHANNELS,
    PUBSUB_CHANNELS,
    channel_kind,
    ChannelKind,
)


def test_channels_total_thirteen() -> None:
    assert len(ALL_CHANNELS) == 13
    assert len(PUBSUB_CHANNELS) == 1
    assert len(ALL_STREAM_CHANNELS) == 12


def test_channel_kind() -> None:
    assert channel_kind(Channel.IMPACT_PROPOSED_INVOICE_INGESTED) is ChannelKind.STREAM
    assert channel_kind(Channel.PROCESSING_STATUS) is ChannelKind.PUBSUB
    assert channel_kind(Channel.INFRA_DEAD_LETTER) is ChannelKind.STREAM
    with pytest.raises(ValueError):
        channel_kind("not-a-channel")


@pytest.mark.asyncio
async def test_local_roundtrip_publish_consume() -> None:
    t = LocalTransport()
    ch = Channel.IMPACT_PROPOSED_INVOICE_INGESTED
    await t.ensure_group(ch, "test-group")
    pub = Publisher(t)
    await pub.publish(ch, {"signal_id": 1, "event_id": "ev-1", "hello": "world"})
    msgs = await t.consume_batch(ch, "test-group", "c1", count=10, block_ms=200)
    assert len(msgs) == 1
    assert msgs[0].payload["hello"] == "world"
    assert msgs[0].signal_id == 1
    await t.ack(ch, "test-group", msgs[0].delivery_id)


@pytest.mark.asyncio
async def test_local_idempotency_dedup() -> None:
    t = LocalTransport()
    ch = Channel.IMPACT_PROPOSED_INVOICE_INGESTED
    await t.ensure_group(ch, "g")
    await t.publish(ch, {"signal_id": 42, "event_id": "ev-42"})
    res = await t.publish(ch, {"signal_id": 42, "event_id": "ev-42-dup"})
    assert res == "duplicate"
    msgs = await t.consume_batch(ch, "g", "c", count=10, block_ms=200)
    assert len(msgs) == 1


@pytest.mark.asyncio
async def test_local_dead_letter_on_publisher_failure() -> None:
    class FailingTransport(LocalTransport):
        async def publish(self, channel, payload):  # type: ignore[override]
            raise RuntimeError("simulated failure")

    t = FailingTransport()
    pub = Publisher(t)
    with pytest.raises(RuntimeError):
        await pub.publish(Channel.IMPACT_PROPOSED_INVOICE_INGESTED, {"signal_id": 7})
    dls = t.dead_letters()
    assert len(dls) >= 1
    assert "simulated failure" in dls[-1]["reason"]


@pytest.mark.asyncio
async def test_consumer_processes_once_with_dedup() -> None:
    t = LocalTransport()
    ch = Channel.IMPACT_RESOLVED_JE_POSTED
    await t.ensure_group(ch, "workers")

    processed: list[ReceivedMessage] = []

    class TestConsumer(Consumer):
        async def handle(self, message: ReceivedMessage) -> None:
            processed.append(message)

    c = TestConsumer(t, ch, "workers", "w1")
    await t.publish(ch, {"signal_id": 1, "event_id": "e1"})
    await t.publish(ch, {"signal_id": 1, "event_id": "e1-dup"})  # dedup'd at publish
    await t.publish(ch, {"signal_id": 2, "event_id": "e2"})
    n = await c.step(block_ms=200, count=10)
    assert n >= 1
    ids = {m.signal_id for m in processed}
    assert ids == {1, 2}


@pytest.mark.asyncio
async def test_consumer_dlqs_after_max_retries() -> None:
    t = LocalTransport()
    ch = Channel.IMPACT_ADVISORY_BUDGET_THRESHOLD
    await t.ensure_group(ch, "wg")

    class BoomConsumer(Consumer):
        max_retries = 2

        async def handle(self, message: ReceivedMessage) -> None:
            raise ValueError("kaboom")

    c = BoomConsumer(t, ch, "wg", "w")
    await t.publish(ch, {"signal_id": 99, "event_id": "e"})
    for _ in range(5):
        await c.step(block_ms=100)
        if t.dead_letters():
            break
    assert any("max_retries_exceeded" in d["reason"] for d in t.dead_letters())


@pytest.mark.asyncio
async def test_local_broadcast_pubsub() -> None:
    t = LocalTransport()
    q = t.subscribe_pubsub(Channel.PROCESSING_STATUS)
    await t.broadcast(Channel.PROCESSING_STATUS, {"status": "ok"})
    msg = await asyncio.wait_for(q.get(), timeout=0.5)
    assert msg["status"] == "ok"


@pytest.mark.asyncio
async def test_pubsub_rejects_stream_channel() -> None:
    t = LocalTransport()
    with pytest.raises(ValueError):
        await t.broadcast(Channel.IMPACT_PROPOSED_INVOICE_INGESTED, {})


@pytest.mark.asyncio
async def test_publish_rejects_pubsub_channel() -> None:
    t = LocalTransport()
    with pytest.raises(ValueError):
        await t.publish(Channel.PROCESSING_STATUS, {})


@pytest.mark.asyncio
async def test_platform_stub_raises_and_health_unhealthy() -> None:
    t = PlatformTransport()
    h = await t.health()
    assert h.backend == "platform"
    assert h.healthy is False
    with pytest.raises(NotImplementedError):
        await t.publish(Channel.IMPACT_PROPOSED_INVOICE_INGESTED, {})


def test_factory_local() -> None:
    os.environ.pop("TRANSPORT_BACKEND", None)
    t = create_transport("local")
    assert t.backend_name == "local"


def test_factory_platform_stub() -> None:
    t = create_transport("platform")
    assert t.backend_name == "platform"


def test_factory_unknown_raises() -> None:
    with pytest.raises(ValueError):
        create_transport("bogus")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("REDIS_INTEGRATION") != "1",
    reason="set REDIS_INTEGRATION=1 with docker-compose redis to run",
)
async def test_redis_roundtrip_integration() -> None:
    from backend.membrane.transport.redis_transport import RedisTransport
    t = RedisTransport()
    ch = Channel.IMPACT_PROPOSED_INVOICE_INGESTED
    await t.ensure_group(ch, "it-group")
    await t.publish(ch, {"signal_id": 1, "event_id": "ev"})
    deadline = asyncio.get_event_loop().time() + 1.0
    msgs: list = []
    while not msgs and asyncio.get_event_loop().time() < deadline:
        msgs = await t.consume_batch(ch, "it-group", "c1", count=10, block_ms=200)
    assert msgs
    h = await t.health()
    assert h.healthy is True
    await t.close()
