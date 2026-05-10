#!/usr/bin/env python3
"""Seed comprehensive test data for all 8 UX flows - simplified version."""

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.db.connection import execute_query
from backend.db.transactions import atomic_transaction
from backend.events.schemas import EventType, TagKind, FinancialEvent
from backend.events.emitter import emit_event_in_txn

CHURCH_ID = "holy_comforter"

def get_church_pk():
    """Get or create church PK."""
    result = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (CHURCH_ID,),
        fetch_one=True
    )
    if result:
        return result.get("id")

    execute_query(
        "INSERT INTO churches (church_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (CHURCH_ID, "Holy Comforter Church")
    )
    result = execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (CHURCH_ID,),
        fetch_one=True
    )
    return result.get("id") if result else None

def seed_all_flows():
    """Seed test data for all 8 flows."""
    print("Starting UX test data seeding...")
    church_pk = get_church_pk()

    if not church_pk:
        print("✗ Failed to get/create church")
        return

    try:
        # FLOW 1: Reconciliation - create bank transactions + JE events
        print("\n=== FLOW 1: Reconciliation ===")
        plaid_result = execute_query(
            """INSERT INTO plaid_accounts
               (church_id, account_id, access_token_enc, account_number, routing_number, account_type, account_subtype, mask, name)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (church_id, account_id) DO NOTHING
               RETURNING id""",
            (church_pk, "checking_001", "encrypted_token", "1234567", "021000021", "depository", "checking", "7890", "Operating Account"),
            fetch_one=True
        )

        if plaid_result:
            account_pk = plaid_result.get("id")
            # Create 50 bank transactions
            for i in range(50):
                txn_date = (datetime.now() - timedelta(days=30-i)).date()
                amount = Decimal(str(100 + (i * 10)))
                execute_query(
                    """INSERT INTO plaid_transactions
                       (txn_id, church_id, account_id, date, description, amount, category, merchant_name, fetched_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (f"plaid_txn_{i:03d}", church_pk, account_pk, txn_date, f"Transaction {i+1}", amount, "TRANSFER", f"Merchant {i}", datetime.utcnow())
                )
            print(f"✓ Created Plaid account + 50 transactions")

        # Create 40 JE events
        for i in range(40):
            ev = FinancialEvent(
                event_type=EventType.TRANSACTION_POSTED,
                church_id=CHURCH_ID,
                payload={
                    "je_id": f"JE-{i:04d}",
                    "date": (datetime.now() - timedelta(days=30-(i%30))).date().isoformat(),
                    "description": f"JE {i+1}",
                    "amount": str(500 + (i*10))
                }
            )
            ev.add_tag(TagKind.ACCOUNT, "1010")
            ev.add_tag(TagKind.PERIOD, f"2026-{(5-(i%5)):02d}")
            with atomic_transaction() as conn:
                emit_event_in_txn(conn, ev)
        print(f"✓ Created 40 JE events")

        # FLOW 2: Payment Approval
        print("\n=== FLOW 2: Payment Approval ===")
        payments = [
            {"amount": 2500, "ministry": "youth_ministry", "beneficiary": "staff"},
            {"amount": 800, "ministry": "facility_maintenance", "beneficiary": "facility"},
            {"amount": 15000, "ministry": "community_outreach", "beneficiary": "community"},
            {"amount": 450, "ministry": "worship", "beneficiary": "congregation"},
            {"amount": 5000, "ministry": "operations", "beneficiary": "staff"},
        ]
        for p in payments:
            ev = FinancialEvent(
                event_type=EventType.PAYMENT_INITIATED,
                church_id=CHURCH_ID,
                payload={"amount": str(p["amount"]), "requested_date": datetime.now().date().isoformat()}
            )
            ev.add_tag(TagKind.MINISTRY, p["ministry"])
            ev.add_tag(TagKind.BENEFICIARY, p["beneficiary"])
            with atomic_transaction() as conn:
                emit_event_in_txn(conn, ev)
        print(f"✓ Created 5 payment approval events")

        # FLOW 3: Q&A Loop
        print("\n=== FLOW 3: Q&A Loop ===")
        ev = FinancialEvent(
            event_type=EventType.DOCUMENT_RECEIVED,
            church_id=CHURCH_ID,
            payload={
                "amount": "3200",
                "description": "Facility rental - multipurpose use",
                "vendor": "Local Property Management",
                "document_id": "INV-2026-AMBIG-001"
            }
        )
        ev.add_tag(TagKind.VENDOR, "Local Property Management")
        ev.add_tag(TagKind.PERIOD, "2026-05")
        with atomic_transaction() as conn:
            emit_event_in_txn(conn, ev)
        print(f"✓ Created ambiguous invoice event")

        # FLOW 4: Semantic Tagging
        print("\n=== FLOW 4: Semantic Tagging ===")
        expenses = [
            {"amount": 500, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-MA"},
            {"amount": 800, "ministry": "community_outreach", "cost_center": "program", "geography": "US-MA"},
            {"amount": 1200, "ministry": "facility_maintenance", "cost_center": "operations", "geography": "US-MA"},
            {"amount": 300, "ministry": "worship", "cost_center": "program", "geography": "US-MA"},
            {"amount": 2500, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-CT"},
            {"amount": 600, "ministry": "community_outreach", "cost_center": "program", "geography": "US-CT"},
            {"amount": 450, "ministry": "operations", "cost_center": "operations", "geography": "US-MA"},
            {"amount": 750, "ministry": "facility_maintenance", "cost_center": "operations", "geography": "US-CT"},
            {"amount": 1500, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-MA"},
            {"amount": 900, "ministry": "worship", "cost_center": "program", "geography": "US-CT"},
            {"amount": 2000, "ministry": "community_outreach", "cost_center": "program", "geography": "US-MA"},
            {"amount": 350, "ministry": "facility_maintenance", "cost_center": "operations", "geography": "US-MA"},
            {"amount": 1100, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-CT"},
            {"amount": 650, "ministry": "worship", "cost_center": "program", "geography": "US-MA"},
            {"amount": 4000, "ministry": "community_outreach", "cost_center": "program", "geography": "US-CT"},
            {"amount": 550, "ministry": "operations", "cost_center": "operations", "geography": "US-CT"},
            {"amount": 1300, "ministry": "facility_maintenance", "cost_center": "operations", "geography": "US-MA"},
            {"amount": 800, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-MA"},
            {"amount": 700, "ministry": "worship", "cost_center": "program", "geography": "US-CT"},
            {"amount": 2200, "ministry": "community_outreach", "cost_center": "program", "geography": "US-MA"},
        ]
        for i, exp in enumerate(expenses):
            ev = FinancialEvent(
                event_type=EventType.DOCUMENT_RECEIVED,
                church_id=CHURCH_ID,
                payload={"amount": str(exp["amount"]), "date": (datetime.now()-timedelta(days=i)).isoformat()}
            )
            ev.add_tag(TagKind.MINISTRY, exp["ministry"])
            ev.add_tag(TagKind.COST_CENTER, exp["cost_center"])
            ev.add_tag(TagKind.GEOGRAPHY, exp["geography"])
            ev.add_tag(TagKind.FUND, "GEN")
            with atomic_transaction() as conn:
                emit_event_in_txn(conn, ev)
        print(f"✓ Created 20 tagged expense events")

        # FLOW 5: Decision Ledger (create decision events)
        print("\n=== FLOW 5: Decision Ledger ===")
        for i in range(15):
            confidence = 0.95 - (i * 0.02)
            ev = FinancialEvent(
                event_type=EventType.DECISION_RECORDED,
                church_id=CHURCH_ID,
                payload={
                    "confidence": str(confidence),
                    "account": "6100",
                    "date": (datetime.now()-timedelta(days=i)).isoformat()
                }
            )
            ev.add_tag(TagKind.ACCOUNT, "6100")
            ev.add_tag(TagKind.PERIOD, "2026-05")
            with atomic_transaction() as conn:
                emit_event_in_txn(conn, ev)
        print(f"✓ Created 15 decision events")

        # FLOW 6: Semantic Reporting (uses Flow 4 data)
        print("\n=== FLOW 6: Semantic Reporting ===")
        print(f"✓ Ready (uses Flow 4 data)")

        # FLOW 7: Covenant Trajectory
        print("\n=== FLOW 7: Covenant Trajectory ===")
        positions = [
            {"month": "2026-01", "cash": 50000},
            {"month": "2026-02", "cash": 55000},
            {"month": "2026-03", "cash": 60000},
            {"month": "2026-04", "cash": 63000},
            {"month": "2026-05", "cash": 66000},
            {"month": "2026-06", "cash": 69000},
            {"month": "2026-07", "cash": 70000},
            {"month": "2026-08", "cash": 71000},
            {"month": "2026-09", "cash": 70000},
            {"month": "2026-10", "cash": 67000},
        ]
        for pos in positions:
            ev = FinancialEvent(
                event_type=EventType.YTD_ADJUSTED,
                church_id=CHURCH_ID,
                payload={
                    "period": pos["month"],
                    "cash_position": str(pos["cash"]),
                    "covenant_threshold": "45000"
                }
            )
            ev.add_tag(TagKind.PERIOD, pos["month"])
            with atomic_transaction() as conn:
                emit_event_in_txn(conn, ev)
        print(f"✓ Created 10 monthly cash position events")

        # FLOW 8: AR Pattern Detection
        print("\n=== FLOW 8: AR Pattern Detection ===")
        customers = [
            {"name": "Customer A", "delay": 0},
            {"name": "Customer B", "delay": 15},
            {"name": "Customer C", "delay": 2},
            {"name": "Customer D", "delay": 1},
            {"name": "Customer E", "delay": 20},
            {"name": "Customer F", "delay": 3},
            {"name": "Customer G", "delay": 0},
            {"name": "Customer H", "delay": 5},
        ]
        for cust in customers:
            ev = FinancialEvent(
                event_type=EventType.DOCUMENT_RECEIVED,
                church_id=CHURCH_ID,
                payload={
                    "customer": cust["name"],
                    "days_outstanding": str(30 + cust["delay"]),
                    "amount": str(1000)
                }
            )
            ev.add_tag(TagKind.VENDOR, cust["name"])
            ev.add_tag(TagKind.PERIOD, "2026-05")
            with atomic_transaction() as conn:
                emit_event_in_txn(conn, ev)
        print(f"✓ Created 8 AR aging events")

        print("\n" + "="*60)
        print("✓ ALL TEST DATA SEEDED SUCCESSFULLY!")
        print("="*60)
        print("\nFlows ready to test:")
        print("  1. GET /api/events?limit=50 (reconciliation)")
        print("  2. GET /api/decisions?category=CODE (payment approval)")
        print("  3. GET /api/events?tag=ministry:youth_ministry (Q&A)")
        print("  4. GET /api/events?tag=ministry:* (semantic tagging)")
        print("  5. GET /api/decisions (audit trail)")
        print("  6. GET /api/events?tag=geography:US-MA (reporting)")
        print("  7. GET /api/events?event_type=YTD_ADJUSTED (covenant)")
        print("  8. GET /api/events?event_type=RECEIVABLE_AGED (AR patterns)")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    seed_all_flows()
