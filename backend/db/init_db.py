#!/usr/bin/env python3
"""Initialize PostgreSQL database for EIME accounting system.

Usage:
    python -m backend.db.init_db           # Initialize (idempotent)
    python -m backend.db.init_db --force   # Drop and recreate all tables

Reads DATABASE_URL from environment (defaults to
postgresql://claude:claude_dev@localhost:5432/eime_accounting).
"""

import os
import sys
from pathlib import Path

# Allow running this file directly (python backend/db/init_db.py) by ensuring
# the package's parent is on sys.path. When invoked via `python -m backend.db.init_db`
# this is a no-op.
_HERE = Path(__file__).resolve().parent
_BACKEND_ROOT = _HERE.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

try:
    # Preferred: package-qualified imports
    from backend.db.connection import init_pool, test_connection, get_connection, return_connection
    from backend.db.migrations import init_schema
    from backend.db.coa_store import ensure_seed
except ImportError:
    # Fallback for running from inside backend/db/
    from connection import init_pool, test_connection, get_connection, return_connection  # type: ignore
    from migrations import init_schema  # type: ignore
    from coa_store import ensure_seed  # type: ignore


def init_database(force: bool = False) -> bool:
    """Initialize the database schema and seed data.

    Args:
        force: If True, drop and recreate all tables.

    Returns:
        True on success, False on failure.
    """
    print("[DB] Initializing EIME database...")

    # 1. Test connectivity
    if not test_connection():
        print("[ERROR] Cannot connect to PostgreSQL. Check DATABASE_URL.")
        print(f"        DATABASE_URL={os.environ.get('DATABASE_URL', '<default>')}")
        return False

    # 2. Initialize schema (creates tables, indexes, schema_version row)
    try:
        init_schema(force=force)
        print("[DB] Schema initialized successfully")
    except Exception as e:
        print(f"[ERROR] Schema initialization failed: {e}")
        return False

    # 3. Seed default churches
    try:
        created = ensure_seed()
        if created:
            print(f"[DB] Seeded churches: {created}")
        else:
            print("[DB] Default churches already present (no seeding needed)")
    except Exception as e:
        print(f"[WARNING] Church seeding failed (may already exist): {e}")

    # 4. Verify tables and report row counts
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()

        print(f"\n[DB] Schema ready with {len(tables)} tables:")
        for table in tables:
            cur = conn.cursor()
            try:
                # Identifier is from pg_tables -> safe to interpolate
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                count = cur.fetchone()[0]
            except Exception as e:
                count = f"ERR ({e})"
            finally:
                cur.close()
            print(f"  - {table}: {count} rows")
        conn.commit()
    finally:
        return_connection(conn)

    print("\n[DB] Database initialization complete!")
    return True


if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    if force_flag:
        print("[DB] --force specified: existing tables WILL be dropped.")
    ok = init_database(force=force_flag)
    sys.exit(0 if ok else 1)
