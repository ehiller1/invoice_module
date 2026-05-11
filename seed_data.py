#!/usr/bin/env python3
"""
Seed script to populate eime_accounting database with test data for development/testing.
"""
import json
import os
from datetime import datetime, timedelta, timezone
import psycopg2

# Database connection
DB_URL = os.getenv('DATABASE_URL', 'postgresql://claude:claude_dev@localhost:5432/eime_accounting')

def get_connection():
    """Get PostgreSQL connection."""
    try:
        conn = psycopg2.connect(DB_URL)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def seed_processing_jobs(conn):
    """Insert test processing jobs (invoices in various stages)."""
    if not conn:
        return

    cur = conn.cursor()

    # Clear existing test data
    cur.execute("DELETE FROM processing_jobs WHERE job_id LIKE 'test_job_%'")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    jobs = [
        {
            'job_id': 'test_job_001',
            'church_id': 2,
            'filename': 'staples_invoice_may2024.pdf',
            'pdf_path': '/tmp/test_invoices/staples_invoice_may2024.pdf',
            'document_type': 'INVOICE',
            'status': 'RECEIVED',
            'created_at': now_iso,
            'updated_at': now_iso,
            'invoice_document': {'vendor': 'Staples', 'amount': 145.50, 'invoice_date': '2024-05-01', 'raw_text': 'Office Supplies Invoice'},
        },
        {
            'job_id': 'test_job_002',
            'church_id': 2,
            'filename': 'duke_energy_bill_may2024.pdf',
            'pdf_path': '/tmp/test_invoices/duke_energy_bill_may2024.pdf',
            'document_type': 'UTILITY_BILL',
            'status': 'EXTRACTING',
            'created_at': (now - timedelta(hours=3)).isoformat(),
            'updated_at': now_iso,
            'invoice_document': {'vendor': 'Duke Energy', 'amount': 2340.00, 'invoice_date': '2024-05-10', 'raw_text': 'Utility Bill - Electricity'},
        },
        {
            'job_id': 'test_job_003',
            'church_id': 2,
            'filename': 'abc_repair_invoice.pdf',
            'pdf_path': '/tmp/test_invoices/abc_repair_invoice.pdf',
            'document_type': 'INVOICE',
            'status': 'CLASSIFYING',
            'created_at': (now - timedelta(hours=5)).isoformat(),
            'updated_at': now_iso,
            'invoice_document': {'vendor': 'ABC Repair Service', 'amount': 890.75, 'invoice_date': '2024-05-08', 'raw_text': 'Equipment Maintenance'},
        },
        {
            'job_id': 'test_job_004',
            'church_id': 2,
            'filename': 'education_supplies.pdf',
            'pdf_path': '/tmp/test_invoices/education_supplies.pdf',
            'document_type': 'INVOICE',
            'status': 'MAPPING',
            'created_at': (now - timedelta(hours=6)).isoformat(),
            'updated_at': now_iso,
            'invoice_document': {'vendor': 'Christian Education Press', 'amount': 275.00, 'invoice_date': '2024-05-09', 'raw_text': 'Sunday School Materials'},
        },
        {
            'job_id': 'test_job_005',
            'church_id': 2,
            'filename': 'membership_directory_printing.pdf',
            'pdf_path': '/tmp/test_invoices/membership_directory_printing.pdf',
            'document_type': 'INVOICE',
            'status': 'REVIEW',
            'created_at': (now - timedelta(hours=8)).isoformat(),
            'updated_at': now_iso,
            'invoice_document': {'vendor': 'PrintMasters Inc', 'amount': 650.00, 'invoice_date': '2024-05-07', 'raw_text': 'Membership Directory Printing'},
        },
        {
            'job_id': 'test_job_006',
            'church_id': 2,
            'filename': 'catering_invoice.pdf',
            'pdf_path': '/tmp/test_invoices/catering_invoice.pdf',
            'document_type': 'INVOICE',
            'status': 'COMPLETING',
            'created_at': (now - timedelta(hours=12)).isoformat(),
            'updated_at': now_iso,
            'invoice_document': {'vendor': 'Mountain View Catering', 'amount': 520.00, 'invoice_date': '2024-05-06', 'raw_text': 'Youth Group Event Catering'},
        },
        {
            'job_id': 'test_job_007',
            'church_id': 2,
            'filename': 'cleaning_supplies.pdf',
            'pdf_path': '/tmp/test_invoices/cleaning_supplies.pdf',
            'document_type': 'INVOICE',
            'status': 'COMPLETING',
            'created_at': (now - timedelta(hours=24)).isoformat(),
            'updated_at': now_iso,
            'invoice_document': {'vendor': 'Building Maintenance Co', 'amount': 180.25, 'invoice_date': '2024-05-05', 'raw_text': 'Sanctuary Cleaning Supplies'},
        },
        {
            'job_id': 'test_job_008',
            'church_id': 2,
            'filename': 'organ_tuning.pdf',
            'pdf_path': '/tmp/test_invoices/organ_tuning.pdf',
            'document_type': 'INVOICE',
            'status': 'FAILED',
            'created_at': (now - timedelta(hours=48)).isoformat(),
            'updated_at': now_iso,
            'invoice_document': {'vendor': 'Professional Music Services', 'amount': 450.00, 'invoice_date': '2024-05-04', 'raw_text': 'Organ Tuning Service'},
            'error_message': 'Invalid GL code mapping for vendor category',
        },
    ]

    for job in jobs:
        cur.execute("""
            INSERT INTO processing_jobs (job_id, church_id, status, payload, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (job['job_id'], 2, job['status'], json.dumps(job), job['created_at'], job['updated_at']))

    conn.commit()
    print(f"✓ Inserted {len(jobs)} processing jobs")

def seed_exception_cards(conn):
    """Insert test exception cards."""
    if not conn:
        return

    cur = conn.cursor()

    # Clear existing test data
    cur.execute("DELETE FROM exception_cards WHERE card_id LIKE 'exc_test_%'")

    now = datetime.now(timezone.utc)
    exceptions = [
        {
            'card_id': 'exc_test_001',
            'church_id': 2,
            'job_id': 'test_job_003',
            'exception_type': 'AMBIGUOUS_CATEGORIZATION',
            'status': 'OPEN',
            'title': 'Equipment Classification Ambiguous',
            'description': 'Item could be capitalized or expensed - requires approval',
            'evidence': {'vendor': 'ABC Repair Service', 'amount': 890.75, 'gl_options': ['5100', '1200']},
            'suggested_action': {'action': 'APPROVE_AS_EXPENSE', 'gl_code': '5100', 'rationale': 'Under $1000 threshold'}
        },
        {
            'card_id': 'exc_test_002',
            'church_id': 2,
            'job_id': 'test_job_005',
            'exception_type': 'BUDGET_OVERAGE',
            'status': 'OPEN',
            'title': 'Budget Overage - Communications',
            'description': 'Printing expense exceeds approved monthly budget by $150',
            'evidence': {'department': 'Communications', 'budget_remaining': 500.0, 'requested': 650.0, 'overage': 150.0},
            'suggested_action': {'action': 'REQUEST_APPROVAL', 'approver_role': 'Treasurer', 'reason': 'Over budget threshold'}
        },
        {
            'card_id': 'exc_test_003',
            'church_id': 2,
            'job_id': None,
            'exception_type': 'POLICY_VIOLATION',
            'status': 'RESOLVED',
            'title': 'Vendor Policy Compliance',
            'description': 'Vendor not on approved vendor list',
            'evidence': {'vendor': 'Mountain View Catering', 'policy': 'Require 3 quotes for > $500'},
            'suggested_action': {'action': 'ADD_VENDOR', 'vendor_id': 'vendor_mvc_001'},
            'assigned_to': 'Finance Manager',
            'resolved_at': (now - timedelta(hours=2)).isoformat(),
            'resolution_data': {'approved_date': datetime.now(timezone.utc).isoformat(), 'approver': 'Treasurer'}
        },
    ]

    for exc in exceptions:
        cur.execute("""
            INSERT INTO exception_cards
            (card_id, church_id, job_id, exception_type, status, title, description, evidence, suggested_action, assigned_to, created_at, resolved_at, resolution_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            exc['card_id'],
            exc['church_id'],
            exc.get('job_id'),
            exc['exception_type'],
            exc['status'],
            exc['title'],
            exc.get('description'),
            json.dumps(exc.get('evidence', {})),
            json.dumps(exc.get('suggested_action', {})),
            exc.get('assigned_to'),
            now,
            exc.get('resolved_at'),
            json.dumps(exc.get('resolution_data', {})) if exc.get('resolution_data') else None
        ))

    conn.commit()
    print(f"✓ Inserted {len(exceptions)} exception cards")

def seed_question_cards(conn):
    """Insert test question cards."""
    if not conn:
        return

    cur = conn.cursor()

    # Clear existing test data
    cur.execute("DELETE FROM question_cards WHERE card_id LIKE 'q_test_%'")

    now = datetime.now(timezone.utc)
    questions = [
        {
            'card_id': 'q_test_001',
            'church_id': 2,
            'question_text': 'Should we capitalize the new projector as equipment or expense it as a supply?',
            'status': 'OPEN',
            'asked_by': 'Admin Staff',
            'assigned_to': 'Treasurer',
            'created_at': now
        },
        {
            'card_id': 'q_test_002',
            'church_id': 2,
            'question_text': 'Which fund should this donation be assigned to?',
            'status': 'OPEN',
            'asked_by': 'Finance Manager',
            'assigned_to': None,
            'created_at': (now - timedelta(hours=3))
        },
        {
            'card_id': 'q_test_003',
            'church_id': 2,
            'question_text': 'Can we use this grant for operational expenses?',
            'status': 'RESOLVED',
            'asked_by': 'Programs Director',
            'assigned_to': 'Treasurer',
            'created_at': (now - timedelta(days=2)),
            'resolved_at': (now - timedelta(days=1)),
            'response': 'Yes, per the grant guidelines section 3.2'
        },
    ]

    for q in questions:
        cur.execute("""
            INSERT INTO question_cards
            (card_id, church_id, question_text, status, asked_by, assigned_to, created_at, resolved_at, response)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            q['card_id'],
            q['church_id'],
            q['question_text'],
            q['status'],
            q.get('asked_by'),
            q.get('assigned_to'),
            q.get('created_at'),
            q.get('resolved_at'),
            q.get('response')
        ))

    conn.commit()
    print(f"✓ Inserted {len(questions)} question cards")

def seed_recommendation_cards(conn):
    """Insert test recommendation cards."""
    if not conn:
        return

    cur = conn.cursor()

    # Clear existing test data
    cur.execute("DELETE FROM recommendation_cards WHERE card_id LIKE 'rec_test_%'")

    now = datetime.now(timezone.utc)
    recommendations = [
        {
            'card_id': 'rec_test_001',
            'church_id': 2,
            'recommendation_type': 'COST_OPTIMIZATION',
            'status': 'OPEN',
            'title': 'Switch to bulk vendor for office supplies',
            'description': 'Current supplier costs 18% above market rate. Bulk purchasing could save $200/month.',
            'impact_score': 85.5,
            'confidence_pct': 92.0,
            'created_at': now
        },
        {
            'card_id': 'rec_test_002',
            'church_id': 2,
            'recommendation_type': 'COMPLIANCE_ALERT',
            'status': 'OPEN',
            'title': 'Update vendor W9 forms',
            'description': '3 vendors have W9 forms expiring this month. Update required for 1099 reporting.',
            'impact_score': 78.0,
            'confidence_pct': 95.0,
            'created_at': (now - timedelta(days=1))
        },
        {
            'card_id': 'rec_test_003',
            'church_id': 2,
            'recommendation_type': 'PROCESS_IMPROVEMENT',
            'status': 'RESOLVED',
            'title': 'Implement monthly reconciliation process',
            'description': 'Establish monthly bank/GL reconciliation to catch discrepancies early.',
            'impact_score': 88.0,
            'confidence_pct': 87.5,
            'created_at': (now - timedelta(days=5)),
            'decided_at': (now - timedelta(days=2)),
            'decision_data': {'decision': 'APPROVED', 'approved_by': 'Finance Committee', 'implementation_date': '2024-06-01'}
        },
    ]

    for rec in recommendations:
        cur.execute("""
            INSERT INTO recommendation_cards
            (card_id, church_id, recommendation_type, status, title, description, impact_score, confidence_pct, created_at, decided_at, decision_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            rec['card_id'],
            rec['church_id'],
            rec['recommendation_type'],
            rec['status'],
            rec['title'],
            rec.get('description'),
            rec.get('impact_score'),
            rec.get('confidence_pct'),
            rec.get('created_at'),
            rec.get('decided_at'),
            json.dumps(rec.get('decision_data', {})) if rec.get('decision_data') else None
        ))

    conn.commit()
    print(f"✓ Inserted {len(recommendations)} recommendation cards")

def main():
    """Run all seed functions."""
    conn = get_connection()
    if not conn:
        print("Failed to connect to database")
        return

    try:
        print("🌱 Seeding eime_accounting database with test data...\n")
        seed_processing_jobs(conn)
        seed_exception_cards(conn)
        seed_question_cards(conn)
        seed_recommendation_cards(conn)
        print("\n✅ Database seeding complete!")
    except Exception as e:
        print(f"❌ Error during seeding: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    main()
