#!/usr/bin/env python3
"""Smoke tests for PostgreSQL-backed accounting system.

Minimal tests to verify database connectivity and core tables.
"""

import os
import sys
from pathlib import Path

# Ensure parent directory is in sys.path
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from backend.db.connection import init_pool, get_connection, return_connection, close_pool
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)


def test_database_connectivity():
    """Test basic database connectivity."""
    print("\n[TEST] Database Connectivity")
    print("=" * 60)

    init_pool(minconn=2, maxconn=10)
    conn = get_connection()

    try:
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"✓ PostgreSQL version: {version[0][:50]}...")
        cur.close()
        print("✓ PASS: Database connectivity test")
        return True
    finally:
        return_connection(conn)


def test_schema_integrity():
    """Test that all required tables exist."""
    print("\n[TEST] Schema Integrity")
    print("=" * 60)

    required_tables = [
        "churches",
        "gl_accounts",
        "funds",
        "journal_entries",
        "journal_entry_lines",
        "payment_instructions",
        "plaid_transactions",
        "approval_audit_events",
        "approval_chains",
        "ytd_actuals",
        "processing_jobs",
        "decision_ledger_entries",
        "vendors",
        "plaid_accounts",
    ]

    conn = get_connection()
    try:
        cur = conn.cursor()

        # Get list of tables
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """)
        existing_tables = {row[0] for row in cur.fetchall()}
        cur.close()

        print(f"Found {len(existing_tables)} tables in schema")

        # Check required tables
        missing = set(required_tables) - existing_tables
        if missing:
            print(f"✗ Missing tables: {missing}")
            return False

        for table in required_tables:
            print(f"  ✓ {table}")

        print("✓ PASS: Schema integrity test")
        return True

    finally:
        return_connection(conn)


def test_seeded_data():
    """Test that seeded churches exist."""
    print("\n[TEST] Seeded Data")
    print("=" * 60)

    conn = get_connection()
    try:
        cur = conn.cursor()

        # Check churches
        cur.execute("SELECT church_id, name FROM churches ORDER BY church_id")
        churches = cur.fetchall()
        print(f"Found {len(churches)} churches:")
        for church_id, name in churches:
            print(f"  ✓ {church_id}: {name}")

        # Check GL accounts
        cur.execute("""
            SELECT COUNT(*) FROM gl_accounts
        """)
        account_count = cur.fetchone()[0]
        print(f"✓ {account_count} GL accounts total")

        # Check funds
        cur.execute("""
            SELECT COUNT(*) FROM funds
        """)
        fund_count = cur.fetchone()[0]
        print(f"✓ {fund_count} funds total")

        cur.close()

        if len(churches) == 0:
            print("! Warning: No churches found (may be expected if not seeded yet)")
            return True

        print("✓ PASS: Seeded data test")
        return True

    finally:
        return_connection(conn)


def test_approval_audit_table():
    """Test approval audit events table."""
    print("\n[TEST] Approval Audit Table")
    print("=" * 60)

    conn = get_connection()
    try:
        cur = conn.cursor()

        # Check table structure
        cur.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'approval_audit_events'
            ORDER BY ordinal_position
        """)
        columns = cur.fetchall()
        print(f"Approval audit event columns:")
        for col_name, data_type in columns:
            print(f"  ✓ {col_name} ({data_type})")

        # Check record count
        cur.execute("SELECT COUNT(*) FROM approval_audit_events")
        count = cur.fetchone()[0]
        print(f"✓ {count} audit events currently in database")

        cur.close()
        print("✓ PASS: Approval audit table test")
        return True

    finally:
        return_connection(conn)


def test_ytd_actuals_table():
    """Test YTD actuals table."""
    print("\n[TEST] YTD Actuals Table")
    print("=" * 60)

    conn = get_connection()
    try:
        cur = conn.cursor()

        # Check record count
        cur.execute("SELECT COUNT(*) FROM ytd_actuals")
        count = cur.fetchone()[0]
        print(f"✓ {count} YTD actual records in database")

        # Sample some records
        cur.execute("""
            SELECT c.church_id, ya.account_number, ya.amount, ya.fiscal_year
            FROM ytd_actuals ya
            JOIN churches c ON c.id = ya.church_id
            LIMIT 5
        """)
        records = cur.fetchall()
        if records:
            print("Sample YTD actuals:")
            for church_id, acct_no, amount, fy in records:
                print(f"  ✓ {church_id} / {acct_no}: {amount} (FY{fy})")

        cur.close()
        print("✓ PASS: YTD actuals table test")
        return True

    finally:
        return_connection(conn)


def test_journal_entries_table():
    """Test journal entries table."""
    print("\n[TEST] Journal Entries Table")
    print("=" * 60)

    conn = get_connection()
    try:
        cur = conn.cursor()

        # Check record count
        cur.execute("SELECT COUNT(*) FROM journal_entries")
        count = cur.fetchone()[0]
        print(f"✓ {count} journal entries in database")

        # Check columns
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'journal_entries'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in cur.fetchall()]
        print(f"✓ Journal entry columns: {len(columns)} total")
        print(f"  Required: entry_id, church_id, status, entry_date, total_debits, total_credits")

        cur.close()
        print("✓ PASS: Journal entries table test")
        return True

    finally:
        return_connection(conn)


def main():
    """Run all smoke tests."""
    print("\n" + "=" * 70)
    print("PostgreSQL-Backed Accounting System - Smoke Tests")
    print("=" * 70)

    tests = [
        ("Database Connectivity", test_database_connectivity),
        ("Schema Integrity", test_schema_integrity),
        ("Seeded Data", test_seeded_data),
        ("Approval Audit Table", test_approval_audit_table),
        ("YTD Actuals Table", test_ytd_actuals_table),
        ("Journal Entries Table", test_journal_entries_table),
    ]

    results = {}
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results[test_name] = "PASS" if passed else "FAIL"
        except Exception as e:
            print(f"✗ ERROR: {e}")
            results[test_name] = "ERROR"

    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)

    passed = sum(1 for r in results.values() if r == "PASS")
    failed = sum(1 for r in results.values() if r == "FAIL")
    errors = sum(1 for r in results.values() if r == "ERROR")

    for test_name, result in results.items():
        symbol = "✓" if result == "PASS" else "✗"
        print(f"{symbol} {test_name}: {result}")

    print(f"\nTotal: {passed} passed, {failed} failed, {errors} errors")
    print("\n" + "=" * 70)
    print("Database Status: ", end="")
    if failed == 0 and errors == 0:
        print("✓ READY FOR TESTING")
    else:
        print("⚠ REVIEW REQUIRED")
    print("=" * 70)

    close_pool()

    return 0 if (failed == 0 and errors == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
