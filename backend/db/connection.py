"""PostgreSQL connection pooling and management."""
import os
from typing import Optional
from psycopg2 import pool
import psycopg2
from contextlib import contextmanager

# Module-level connection pool
_pool: Optional[pool.SimpleConnectionPool] = None

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://claude:claude_dev@localhost:5432/eime_accounting"
)


def init_pool(minconn: int = 2, maxconn: int = 10) -> None:
    """Initialize the connection pool."""
    global _pool
    if _pool is not None:
        return  # Already initialized

    try:
        _pool = pool.SimpleConnectionPool(
            minconn,
            maxconn,
            DATABASE_URL,
            connect_timeout=5
        )
        print(f"[DB] Connection pool initialized: {minconn}-{maxconn} connections to {DATABASE_URL.split('@')[1]}")
    except Exception as e:
        print(f"[DB] Failed to initialize connection pool: {e}")
        raise


def get_connection():
    """Get a connection from the pool."""
    global _pool
    if _pool is None:
        init_pool()

    try:
        conn = _pool.getconn()
        conn.autocommit = False  # Use explicit transactions
        return conn
    except pool.PoolError as e:
        print(f"[DB] Connection pool exhausted: {e}")
        raise


def return_connection(conn) -> None:
    """Return a connection to the pool."""
    global _pool
    if _pool is not None and conn is not None:
        _pool.putconn(conn)


def close_pool() -> None:
    """Close all connections in the pool."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        print("[DB] Connection pool closed")


@contextmanager
def transaction(autocommit: bool = False):
    """Context manager for database transactions.

    Usage:
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(...)
            conn.commit()

    Args:
        autocommit: If True, automatically commit on success. If False, caller must commit.

    Yields:
        Connection object.

    Raises:
        On exception: automatic ROLLBACK; connection returned to pool.
    """
    conn = get_connection()
    try:
        yield conn
        if autocommit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB] Transaction rolled back due to error: {e}")
        raise
    finally:
        return_connection(conn)


def execute_query(query: str, params: tuple = (), fetch_one: bool = False):
    """Execute a query and return results.

    Args:
        query: SQL query with %s placeholders
        params: Query parameters
        fetch_one: If True, return one row; if False, return all rows

    Returns:
        Single row (dict) if fetch_one=True, list of dicts if fetch_one=False, or count for INSERT/UPDATE/DELETE
    """
    with transaction() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)

            # INSERT/UPDATE/DELETE return row count
            if cursor.description is None:
                count = cursor.rowcount
                conn.commit()
                return count

            # SELECT queries
            if fetch_one:
                row = cursor.fetchone()
                conn.commit()
                if row is None:
                    return None
                # Convert to dict
                cols = [desc[0] for desc in cursor.description]
                return dict(zip(cols, row))
            else:
                rows = cursor.fetchall()
                conn.commit()
                cols = [desc[0] for desc in cursor.description]
                return [dict(zip(cols, row)) for row in rows]
        finally:
            cursor.close()


def test_connection() -> bool:
    """Test database connectivity."""
    try:
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
        print("[DB] Connection test successful")
        return True
    except Exception as e:
        print(f"[DB] Connection test failed: {e}")
        return False
