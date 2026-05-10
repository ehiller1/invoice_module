"""Fixtures for Phase 5 UX flow tests."""
import pytest
from decimal import Decimal
from backend.db import connection


@pytest.fixture(scope="function")
def test_church_phase5():
    """Create a test church for Phase 5 validation."""
    church_id = "test_church_phase5"

    # Clean up any existing test church
    connection.execute_query(
        "DELETE FROM churches WHERE church_id = %s",
        (church_id,)
    )

    # Create test church
    result = connection.execute_query(
        """
        INSERT INTO churches (church_id, name, denomination_type, created_at)
        VALUES (%s, %s, %s, NOW())
        RETURNING id
        """,
        (church_id, "Test Church Phase 5", "EPISCOPAL")
    )

    church_pk = result[0]['id'] if result else None
    yield church_id, church_pk

    # Cleanup
    connection.execute_query(
        "DELETE FROM churches WHERE church_id = %s",
        (church_id,)
    )


@pytest.fixture(scope="function")
def test_church_citations():
    """Create a test church for decision ledger citation tests."""
    church_id = "test_church_citations"

    # Clean up any existing test church
    connection.execute_query(
        "DELETE FROM churches WHERE church_id = %s",
        (church_id,)
    )

    # Create test church
    result = connection.execute_query(
        """
        INSERT INTO churches (church_id, name, denomination_type, created_at)
        VALUES (%s, %s, %s, NOW())
        RETURNING id
        """,
        (church_id, "Test Church Citations", "EPISCOPAL")
    )

    church_pk = result[0]['id'] if result else None
    yield church_id, church_pk

    # Cleanup
    connection.execute_query(
        "DELETE FROM churches WHERE church_id = %s",
        (church_id,)
    )


@pytest.fixture(scope="function")
def seeded_church():
    """Load or create the holy_comforter seeded test data."""
    church_id = "holy_comforter_test"

    # Clean up any existing instance
    connection.execute_query(
        "DELETE FROM churches WHERE church_id = %s",
        (church_id,)
    )

    # Create seeded church
    result = connection.execute_query(
        """
        INSERT INTO churches (church_id, name, denomination_type, created_at)
        VALUES (%s, %s, %s, NOW())
        RETURNING id
        """,
        (church_id, "Holy Comforter Test", "EPISCOPAL")
    )

    church_pk = result[0]['id'] if result else None

    # Seed a basic GL account for testing
    if church_pk:
        connection.execute_query(
            """
            INSERT INTO gl_accounts (church_id, account_number, name, account_type, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (church_id, account_number) DO NOTHING
            """,
            (church_pk, "7200", "Utilities - Electric", "EXPENSE")
        )

    yield church_id, church_pk

    # Cleanup
    connection.execute_query(
        "DELETE FROM churches WHERE church_id = %s",
        (church_id,)
    )
