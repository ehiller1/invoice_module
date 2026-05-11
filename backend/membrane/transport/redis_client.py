"""Shared async redis-py client singleton (Phase 2)."""
from __future__ import annotations

import os
from typing import Optional

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover — redis is optional in CI
    aioredis = None  # type: ignore


DEFAULT_REDIS_URL = "redis://localhost:6379/0"


_client: Optional["aioredis.Redis"] = None  # type: ignore[name-defined]


def get_redis_url() -> str:
    return os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)


def get_redis_client():  # type: ignore[no-untyped-def]
    """Return a cached async Redis client."""
    global _client
    if aioredis is None:
        raise RuntimeError("redis-py not installed; install `redis>=5.2`")
    if _client is None:
        _client = aioredis.from_url(
            get_redis_url(),
            encoding="utf-8",
            decode_responses=True,
        )
    return _client


async def close_redis_client() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None


def reset_for_tests() -> None:
    """Drop the cached singleton (used by test fixtures)."""
    global _client
    _client = None


__all__ = [
    "DEFAULT_REDIS_URL",
    "get_redis_client",
    "get_redis_url",
    "close_redis_client",
    "reset_for_tests",
]
