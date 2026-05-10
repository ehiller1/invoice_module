"""Database schema migrations and version management."""
import os
from pathlib import Path
from .connection import get_connection, transaction

MIGRATIONS_DIR = Path(__file__).parent


def check_schema_version() -> int:
    """Get current schema version from database."""
    with transaction() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MAX(version) FROM schema_version")
            result = cursor.fetchone()
            version = result[0] if result and result[0] else 0
            cursor.close()
            return version
        except Exception as e:
            print(f"[DB] Schema check failed (expected on first run): {e}")
            return 0


def run_migrations() -> None:
    """Run all pending migrations.

    Migrations are SQL files in the migrations/ directory with numeric prefixes.
    Example: migrations/001_initial_schema.sql, migrations/002_add_encryption.sql

    Idempotent: tracks applied migrations and only runs pending ones.
    """
    current_version = check_schema_version()
    print(f"[DB] Current schema version: {current_version}")

    migrations_dir = MIGRATIONS_DIR / "migrations"
    if not migrations_dir.exists():
        print(f"[DB] Migrations directory not found: {migrations_dir}")
        return

    # Find all migration files
    migration_files = sorted([
        f for f in migrations_dir.glob("*.sql")
        if f.name[0].isdigit()
    ])

    if not migration_files:
        print("[DB] No migrations found")
        return

    for migration_file in migration_files:
        # Extract version from filename (e.g., "001_initial_schema.sql" -> 1)
        try:
            version = int(migration_file.stem.split("_")[0])
        except ValueError:
            print(f"[DB] Skipping invalid migration filename: {migration_file.name}")
            continue

        if version <= current_version:
            continue  # Already applied

        print(f"[DB] Running migration {version}: {migration_file.name}")

        try:
            sql = migration_file.read_text()
            with transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                # Record the migration
                cursor.execute(
                    "INSERT INTO schema_version (version, description) VALUES (%s, %s)",
                    (version, migration_file.stem)
                )
                conn.commit()
                cursor.close()
            print(f"[DB] Migration {version} applied successfully")
        except Exception as e:
            print(f"[DB] Migration {version} failed: {e}")
            raise


def init_schema(force: bool = False) -> None:
    """Initialize schema from schema.sql.

    Args:
        force: If True, drop and recreate all tables.
    """
    schema_file = MIGRATIONS_DIR / "schema.sql"
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    sql = schema_file.read_text()

    with transaction() as conn:
        cursor = conn.cursor()

        if force:
            print("[DB] Dropping existing schema...")
            # Drop all tables (CASCADE deletes dependent objects)
            cursor.execute("""
                SELECT tablename FROM pg_tables
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            """)
            tables = cursor.fetchall()
            for (table,) in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

            # Drop enum types
            cursor.execute("""
                SELECT enumlabel FROM pg_enum
                WHERE enumtypid IN (
                    SELECT oid FROM pg_type
                    WHERE typname IN ('je_status', 'payment_status', 'decision_category', 'decision_outcome', 'processing_status')
                )
            """)
            # Actually, just drop the types
            for enum_type in ['je_status', 'payment_status', 'decision_category', 'decision_outcome', 'processing_status']:
                try:
                    cursor.execute(f"DROP TYPE IF EXISTS {enum_type} CASCADE")
                except Exception:
                    pass  # Type may not exist
            conn.commit()

        print("[DB] Creating schema...")
        cursor.execute(sql)
        conn.commit()
        cursor.close()

    print("[DB] Schema initialization complete")
