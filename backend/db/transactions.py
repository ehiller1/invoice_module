"""Transaction management for atomic database operations."""
from contextlib import contextmanager
from .connection import get_connection, return_connection


@contextmanager
def atomic_transaction():
    """Context manager for atomic database operations.

    Usage:
        with atomic_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(...)
            cursor.execute(...)
            # Commits automatically on success, rolls back on exception

    Yields:
        Database connection with explicit transaction control.

    Raises:
        On exception: automatic ROLLBACK; connection returned to pool.
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        return_connection(conn)


@contextmanager
def savepoint(conn, name: str = "sp"):
    """Context manager for savepoints (nested transactions).

    Usage:
        with atomic_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(...)

            with savepoint(conn, "update_attempt"):
                cursor.execute(...)  # This can fail and be rolled back
                # without losing outer transaction

    Args:
        conn: Database connection
        name: Savepoint name (must be unique within transaction)

    Yields:
        Database connection.

    Raises:
        On exception within the with block: savepoint is rolled back.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(f"SAVEPOINT {name}")
        yield conn
        cursor.execute(f"RELEASE SAVEPOINT {name}")
    except Exception as e:
        cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")
        raise
    finally:
        cursor.close()
