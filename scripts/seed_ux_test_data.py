#!/usr/bin/env python3
"""Seed comprehensive test data for all 8 UX flows."""

import sys
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import uuid

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

def seed_flow1_reconciliation():
    """Flow 1: Reconciliation with real bank feed.

    - 50 bank transactions (Plaid-like)
    - 40 journal entries
    - 5-10 intentional mismatches for exception handling
    """
    print("\n=== FLOW 1: Reconciliation Data ===")
    church_pk = get_church_pk()

    # Create Plaid account
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
        account_pk = plaid_result["id"]
        # Seed 50 Plaid transactions
        base_date = datetime.now() - timedelta(days=30)
        for i in range(50):
            txn_date = base_date + timedelta(days=i)
            amount = Decimal(str(100 + (i * 10)))
            description = f"Transaction {i+1}"

            execute_query(
                """INSERT INTO plaid_transactions
                   (txn_id, church_id, account_id, date, description, amount, category, merchant_name, fetched_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (f"plaid_txn_{i:03d}", church_pk, account_pk, txn_date.date(), description, amount, "TRANSFER", f"Merchant {i}", datetime.utcnow())
            )

    # Create 40 matching journal entry events
    for i in range(40):
        je_ev = FinancialEvent(
            event_type=EventType.JE_POSTED,
            church_id=CHURCH_ID,
            payload={
                "je_id": f"JE-{i:04d}",
                "date": (datetime.now() - timedelta(days=30 - (i % 30))).date().isoformat(),
                "description": f"JE {i+1}",
                "amount": str(500 + (i * 10))
            }
        )
        je_ev.add_tag(TagKind.ACCOUNT, "1010")
        je_ev.add_tag(TagKind.PERIOD, f"2026-{(5 - (i % 5)):02d}")

        with atomic_transaction() as conn:
            emit_event_in_txn(conn, je_ev)

    print(f"✓ Created Plaid account + 50 transactions + 40 JE events")

def seed_flow2_payment_approval():
    """Flow 2: Payment approval with dynamic COA routing.

    - 5 payment scenarios with different ministries/cost centers
    - Each should route to different approver based on amount + ministry
    """
    print("\n=== FLOW 2: Payment Approval Data ===")
    church_pk = get_church_pk()

    payments = [
        {"amount": 2500, "ministry": "youth_ministry", "beneficiary": "staff", "description": "Youth director salary"},
        {"amount": 800, "ministry": "facility_maintenance", "beneficiary": "facility", "description": "HVAC service"},
        {"amount": 15000, "ministry": "community_outreach", "beneficiary": "community", "description": "Food bank donation"},
        {"amount": 450, "ministry": "worship", "beneficiary": "congregation", "description": "Worship supplies"},
        {"amount": 5000, "ministry": "operations", "beneficiary": "staff", "description": "Insurance premium"},
    ]

    for i, p in enumerate(payments):
        # Create as events
        ev = FinancialEvent(
            event_type=EventType.PAYMENT_INITIATED,
            church_id=CHURCH_ID,
            payload={
                "amount": str(p["amount"]),
                "description": p["description"],
                "requested_date": datetime.now().date().isoformat()
            }
        )
        ev.add_tag(TagKind.MINISTRY, p["ministry"])
        ev.add_tag(TagKind.BENEFICIARY, p["beneficiary"])
        ev.add_tag(TagKind.COST_CENTER, "operations" if p["amount"] > 3000 else "program")

        # Store event
        with atomic_transaction() as conn:
            emit_event_in_txn(conn, ev)

    print(f"✓ Created 5 payment approval scenarios with ministry/cost_center tags")

def seed_flow3_qa_loop():
    """Flow 3: Transaction Q&A with ambiguous classification.

    - 1 ambiguous invoice (facility rental - could be ministry or operations)
    - 3 similar historical decisions with different choices
    - Show decision ledger with confidence
    """
    print("\n=== FLOW 3: Q&A Loop Data ===")
    church_pk = get_church_pk()

    # Create ambiguous invoice event
    ambiguous_event = FinancialEvent(
        event_type=EventType.INVOICE_RECEIVED,
        church_id=CHURCH_ID,
        payload={
            "amount": "3200",
            "description": "Facility rental - multipurpose use",
            "vendor": "Local Property Management",
            "document_id": "INV-2026-AMBIG-001"
        }
    )
    ambiguous_event.add_tag(TagKind.VENDOR, "Local Property Management")
    ambiguous_event.add_tag(TagKind.PERIOD, "2026-05")

    with atomic_transaction() as conn:
        emit_event_in_txn(conn, ambiguous_event)

    # Create 3 historical similar decisions with different outcomes + confidence
    for i, decision_choice in enumerate(["ministry_facility", "operations_rent", "ministry_facility"]):
        confidence = 0.95 if i < 2 else 0.60  # Last one is low confidence
        account = "6200" if decision_choice == "ministry_facility" else "6100"

        entry = decision_ledger_store.create_entry(
            church_id=CHURCH_ID,
            category=DecisionCategory.CODE,
            decision_id=f"ambig_decision_{i}",
            reasoning=f"Similar facility use classified as {decision_choice}",
            confidence=confidence,
            alternatives=[
                {"account": "6200", "description": "Ministry facility", "score": 0.65},
                {"account": "6100", "description": "Operations rent", "score": 0.35}
            ],
            evidence={"similar_txns": 3, "pattern": "quarterly_facility"}
        )

    print(f"✓ Created ambiguous invoice + 3 historical decisions with confidence levels")

def seed_flow4_semantic_tagging():
    """Flow 4: Event tagging & multi-dimensional queries.

    - 20 mixed expenses with overlapping dimensions
    - Youth, outreach, facility, admin across different cost centers and geographies
    """
    print("\n=== FLOW 4: Semantic Tagging Data ===")
    church_pk = get_church_pk()

    expenses = [
        {"amount": 500, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-MA", "description": "Youth event"},
        {"amount": 800, "ministry": "community_outreach", "cost_center": "program", "geography": "US-MA", "description": "Food bank supplies"},
        {"amount": 1200, "ministry": "facility_maintenance", "cost_center": "operations", "geography": "US-MA", "description": "HVAC repair"},
        {"amount": 300, "ministry": "worship", "cost_center": "program", "geography": "US-MA", "description": "Bulletin printing"},
        {"amount": 2500, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-CT", "description": "Retreat venue"},
        {"amount": 600, "ministry": "community_outreach", "cost_center": "program", "geography": "US-CT", "description": "Community event"},
        {"amount": 450, "ministry": "operations", "cost_center": "operations", "geography": "US-MA", "description": "Insurance"},
        {"amount": 750, "ministry": "facility_maintenance", "cost_center": "operations", "geography": "US-CT", "description": "Cleaning supplies"},
        {"amount": 1500, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-MA", "description": "Mentor program"},
        {"amount": 900, "ministry": "worship", "cost_center": "program", "geography": "US-CT", "description": "Music licensing"},
        {"amount": 2000, "ministry": "community_outreach", "cost_center": "program", "geography": "US-MA", "description": "Outreach coordinator salary"},
        {"amount": 350, "ministry": "facility_maintenance", "cost_center": "operations", "geography": "US-MA", "description": "Maintenance supplies"},
        {"amount": 1100, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-CT", "description": "Youth group outing"},
        {"amount": 650, "ministry": "worship", "cost_center": "program", "geography": "US-MA", "description": "Organ maintenance"},
        {"amount": 4000, "ministry": "community_outreach", "cost_center": "program", "geography": "US-CT", "description": "Homeless shelter donation"},
        {"amount": 550, "ministry": "operations", "cost_center": "operations", "geography": "US-CT", "description": "Utilities"},
        {"amount": 1300, "ministry": "facility_maintenance", "cost_center": "operations", "geography": "US-MA", "description": "Roof inspection"},
        {"amount": 800, "ministry": "youth_ministry", "cost_center": "program", "geography": "US-MA", "description": "Summer camp"},
        {"amount": 700, "ministry": "worship", "cost_center": "program", "geography": "US-CT", "description": "Candles and supplies"},
        {"amount": 2200, "ministry": "community_outreach", "cost_center": "program", "geography": "US-MA", "description": "Community center lease"},
    ]

    for i, exp in enumerate(expenses):
        ev = FinancialEvent(
            event_type=EventType.EXPENSE_LOGGED,
            church_id=CHURCH_ID,
            payload={
                "amount": str(exp["amount"]),
                "description": exp["description"],
                "date": (datetime.now() - timedelta(days=i)).isoformat()
            }
        )
        ev.add_tag(TagKind.MINISTRY, exp["ministry"])
        ev.add_tag(TagKind.COST_CENTER, exp["cost_center"])
        ev.add_tag(TagKind.GEOGRAPHY, exp["geography"])
        ev.add_tag(TagKind.FUND, "GEN")

        with atomic_transaction() as conn:
            emit_event_in_txn(conn, ev)

    print(f"✓ Created 20 tagged expenses across dimensions (ministry, cost_center, geography)")

def seed_flow5_decision_ledger():
    """Flow 5: Decision ledger with audit trail.

    Create decision-related events that will show reasoning, confidence, alternatives.
    (Decision ledger entries are created by the backend during event processing.)
    """
    print("\n=== FLOW 5: Decision Ledger Data ===")
    church_pk = get_church_pk()

    # Create events that represent decisions (these will have decision_ledger entries)
    decision_events = [
        {"type": "INVOICE_RECEIVED", "confidence": 0.95, "account": "4000"},
        {"type": "EXPENSE_LOGGED", "confidence": 0.72, "account": "6100"},
        {"type": "REVENUE_RECOGNIZED", "confidence": 0.98, "account": "4000"},
        {"type": "PAYMENT_INITIATED", "confidence": 0.88, "account": "2100"},
        {"type": "EXPENSE_LOGGED", "confidence": 0.55, "account": "6200"},
        {"type": "RECEIVABLE_AGED", "confidence": 0.92, "account": "1200"},
        {"type": "INVOICE_RECEIVED", "confidence": 0.81, "account": "2100"},
        {"type": "PAYMENT_INITIATED", "confidence": 0.99, "account": "2000"},
        {"type": "ACCRUAL_ESTIMATED", "confidence": 0.68, "account": "7000"},
        {"type": "REVENUE_RECOGNIZED", "confidence": 0.91, "account": "4000"},
        {"type": "EXPENSE_LOGGED", "confidence": 0.45, "account": "6300"},
        {"type": "INVOICE_RECEIVED", "confidence": 0.85, "account": "5100"},
        {"type": "PAYMENT_INITIATED", "confidence": 0.79, "account": "5000"},
        {"type": "REVENUE_RECOGNIZED", "confidence": 0.88, "account": "4100"},
        {"type": "EXPENSE_LOGGED", "confidence": 0.63, "account": "1020"},
    ]

    for i, dec_ev in enumerate(decision_events):
        ev = FinancialEvent(
            event_type=EventType[dec_ev["type"]],
            church_id=CHURCH_ID,
            payload={
                "confidence": str(dec_ev["confidence"]),
                "suggested_account": dec_ev["account"],
                "reasoning": f"Decision based on pattern matching and policy rules",
                "date": (datetime.now() - timedelta(days=i)).isoformat()
            }
        )
        ev.add_tag(TagKind.ACCOUNT, dec_ev["account"])
        ev.add_tag(TagKind.PERIOD, "2026-05")

        with atomic_transaction() as conn:
            emit_event_in_txn(conn, ev)

    print(f"✓ Created 15 decision events with varied confidence levels")

def seed_flow6_semantic_reporting():
    """Flow 6: Semantic reporting (same data as Flow 4, different queries).

    Data already seeded in Flow 4 - just need to test queries.
    """
    print("\n=== FLOW 6: Semantic Reporting (uses Flow 4 data) ===")
    print(f"✓ Ready to test dimensional queries (ministry, geography, cost_center)")

def seed_flow7_covenant_trajectory():
    """Flow 7: Covenant trajectory via continuous events.

    - Monthly cash flow pattern (15 data points)
    - Covenant threshold definition
    - Alert if trajectory breaches
    """
    print("\n=== FLOW 7: Covenant Trajectory Data ===")
    church_pk = get_church_pk()

    # Create monthly cash position events
    monthly_positions = [
        {"month": "2026-01", "cash": 50000, "revenue": 25000, "expenses": 20000},
        {"month": "2026-02", "cash": 55000, "revenue": 26000, "expenses": 21000},
        {"month": "2026-03", "cash": 60000, "revenue": 28000, "expenses": 23000},
        {"month": "2026-04", "cash": 63000, "revenue": 25000, "expenses": 22000},
        {"month": "2026-05", "cash": 66000, "revenue": 24000, "expenses": 21000},
        {"month": "2026-06", "cash": 69000, "revenue": 22000, "expenses": 21000},
        {"month": "2026-07", "cash": 70000, "revenue": 20000, "expenses": 19000},
        {"month": "2026-08", "cash": 71000, "revenue": 18000, "expenses": 19000},
        {"month": "2026-09", "cash": 70000, "revenue": 15000, "expenses": 18000},
        {"month": "2026-10", "cash": 67000, "revenue": 14000, "expenses": 18000},
    ]

    for pos in monthly_positions:
        ev = FinancialEvent(
            event_type=EventType.ACCRUAL_ESTIMATED,
            church_id=CHURCH_ID,
            payload={
                "period": pos["month"],
                "cash_position": str(pos["cash"]),
                "monthly_revenue": str(pos["revenue"]),
                "monthly_expenses": str(pos["expenses"]),
                "covenant_threshold": "45000",
                "current_trajectory": "declining"
            }
        )
        ev.add_tag(TagKind.PERIOD, pos["month"])

        with atomic_transaction() as conn:
            emit_event_in_txn(conn, ev)

    print(f"✓ Created 10 monthly cash position events showing declining trajectory")

def seed_flow8_ar_pattern_detection():
    """Flow 8: AR aging pattern change detection.

    - 8 customers with historical payment patterns
    - 2 customers showing recent payment delays
    - Pattern anomaly detection ready to trigger
    """
    print("\n=== FLOW 8: AR Pattern Detection Data ===")
    church_pk = get_church_pk()

    customers = [
        {"name": "Customer A", "recent_delay": False, "days_late": 0},
        {"name": "Customer B", "recent_delay": True, "days_late": 15},
        {"name": "Customer C", "recent_delay": False, "days_late": 2},
        {"name": "Customer D", "recent_delay": False, "days_late": 1},
        {"name": "Customer E", "recent_delay": True, "days_late": 20},
        {"name": "Customer F", "recent_delay": False, "days_late": 3},
        {"name": "Customer G", "recent_delay": False, "days_late": 0},
        {"name": "Customer H", "recent_delay": False, "days_late": 5},
    ]

    for cust in customers:
        ev = FinancialEvent(
            event_type=EventType.RECEIVABLE_AGED,
            church_id=CHURCH_ID,
            payload={
                "customer": cust["name"],
                "days_outstanding": str(30 + cust["days_late"]),
                "amount": str(1000 + (customers.index(cust) * 100)),
                "recent_pattern_change": "yes" if cust["recent_delay"] else "no"
            }
        )
        ev.add_tag(TagKind.VENDOR, cust["name"])
        ev.add_tag(TagKind.PERIOD, "2026-05")

        with atomic_transaction() as conn:
            emit_event_in_txn(conn, ev)

    print(f"✓ Created 8 AR aging events (2 showing payment pattern changes)")

def main():
    """Seed all test data for 8 UX flows."""
    print("Starting UX test data seeding...")

    try:
        seed_flow1_reconciliation()
        seed_flow2_payment_approval()
        seed_flow3_qa_loop()
        seed_flow4_semantic_tagging()
        seed_flow5_decision_ledger()
        seed_flow6_semantic_reporting()
        seed_flow7_covenant_trajectory()
        seed_flow8_ar_pattern_detection()

        print("\n" + "="*50)
        print("✓ All test data seeded successfully!")
        print("="*50)
        print("\nReady to test flows:")
        print("  1. GET /api/events?limit=50 (reconciliation)")
        print("  2. /api/decisions?category=CODE (payment approval)")
        print("  3. GET /api/events?tag=ministry:youth_ministry (Q&A)")
        print("  4. GET /api/events?tag=ministry:* (semantic tagging)")
        print("  5. GET /api/decisions (audit trail)")
        print("  6. GET /api/events?tag=geography:US-MA (reporting)")
        print("  7. GET /api/events?event_type=ACCRUAL_ESTIMATED (covenant)")
        print("  8. GET /api/events?event_type=RECEIVABLE_AGED (AR patterns)")

    except Exception as e:
        print(f"✗ Error seeding data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
