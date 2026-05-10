#!/usr/bin/env python3
"""Test all 8 UX flows and document frictions."""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8001"

def test_flow(number, name, endpoint, description):
    """Test a single flow and document experience."""
    print(f"\n{'='*70}")
    print(f"FLOW {number}: {name}")
    print(f"{'='*70}")
    print(f"Description: {description}")
    print(f"Endpoint: {endpoint}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")

    try:
        response = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            # Analyze response structure
            if "total" in data:
                print(f"Total records: {data.get('total', 0)}")
            if "events" in data:
                print(f"Events returned: {len(data.get('events', []))}")
                if data.get('events'):
                    print(f"  First event: {json.dumps(data['events'][0], indent=2, default=str)[:300]}...")
            if "decisions" in data:
                print(f"Decisions returned: {len(data.get('decisions', []))}")
                if data.get('decisions'):
                    print(f"  First decision: {json.dumps(data['decisions'][0], indent=2, default=str)[:300]}...")

            print("\n✓ API WORKS")
            return True
        else:
            print(f"✗ Error: {response.text[:500]}")
            return False
    except Exception as e:
        print(f"✗ Exception: {e}")
        return False

def main():
    print("\n" + "="*70)
    print("UX FLOW TESTING - All 8 Flows")
    print("="*70)

    flows = [
        (1, "Reconciliation", "/api/events?limit=50",
         "Load bank feed events + JE events, watch auto-match exceptions"),

        (2, "Payment Approval", "/api/decisions?limit=20",
         "Query decision ledger, see payment routing by ministry/cost_center"),

        (3, "Transaction Q&A", "/api/events?tag=ministry:youth_ministry",
         "User queries ambiguous transaction, gets recommendations via tags"),

        (4, "Semantic Tagging", "/api/events?tag=ministry:community_outreach&tag=geography:US-MA",
         "Filter events by multiple dimensions (ministry + geography)"),

        (5, "Decision Ledger", "/api/decisions",
         "View audit trail with reasoning, confidence, alternatives"),

        (6, "Semantic Reporting", "/api/events?tag=geography:US-MA",
         "Generate revenue/expense report by geography dimension"),

        (7, "Covenant Trajectory", "/api/events?event_type=YTD_ADJUSTED",
         "Monitor continuous covenant position via events"),

        (8, "AR Pattern Detection", "/api/events?tag=vendor:*",
         "Detect payment pattern changes in customer AR aging"),
    ]

    results = []
    for flow in flows:
        result = test_flow(*flow)
        results.append((flow[0], flow[1], result))

    # Summary
    print("\n\n" + "="*70)
    print("SUMMARY: UX Flow Test Results")
    print("="*70)

    for flow_num, flow_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"Flow {flow_num}: {flow_name:<30} {status}")

    passed_count = sum(1 for _, _, p in results if p)
    print(f"\nTotal: {passed_count}/8 flows working\n")

    if passed_count == 8:
        print("✓ ALL FLOWS FUNCTIONAL - Ready for detailed UX testing")
    else:
        print(f"⚠ {8-passed_count} flows need attention")

if __name__ == "__main__":
    main()
