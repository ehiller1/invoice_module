"""Shared pytest fixtures.

Phase 2: install LocalTransport + LocalEventQuery singletons so any test
that touches the membrane transport layer gets a clean in-process backend.
"""
from __future__ import annotations

import pytest

from backend.membrane.event_query import (
    LocalEventQuery,
    init_query_transport,
    reset_query_transport_for_tests,
)
from backend.membrane.transport import (
    LocalTransport,
    init_transport,
    reset_transport_for_tests,
)


@pytest.fixture
def local_transport() -> LocalTransport:
    reset_transport_for_tests()
    return init_transport(LocalTransport())  # type: ignore[return-value]


@pytest.fixture
def local_event_query() -> LocalEventQuery:
    reset_query_transport_for_tests()
    return init_query_transport(LocalEventQuery())  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _reset_membrane_singletons():
    reset_transport_for_tests()
    reset_query_transport_for_tests()
    yield
    reset_transport_for_tests()
    reset_query_transport_for_tests()
