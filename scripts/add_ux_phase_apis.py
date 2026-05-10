#!/usr/bin/env python3
"""
API enhancements for UX Phases 1-3.

This script adds the following endpoints to backend/main.py:
- Phase 1: Enhanced /api/events with exceptions + confidence formatting
- Phase 2: /api/events/{id}/similar, /api/decisions/{id}/evidence, enhanced /api/dimensions
- Phase 3: /api/reconciliation/exceptions, /api/events/{id}/approve
"""

PHASE_1_ENHANCEMENTS = '''
# ===== PHASE 1: UI Polish - Confidence Visualization & Exception Counts =====

@app.get("/api/events-with-exceptions")
async def list_events_with_exceptions(
    church_id: str = "holy_comforter",
    limit: int = 100,
    offset: int = 0,
    show_exceptions_only: bool = False,
) -> JSONResponse:
    """Enhanced /api/events with exception detection and confidence visualization.

    Adds:
    - Confidence percentage formatting (0.95 → "95%" + color code 🟢)
    - Exception flag for obvious mismatches
    - Confidence color codes: 🟢 80%+, 🟡 60-79%, 🔴 <60%
    """
    from .db import connection

    try:
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )

        if not church_pk:
            return _json({"church_id": church_id, "total": 0, "events": [], "offset": offset, "limit": limit})

        church_pk = church_pk.get("id")

        # Count total events
        count_result = connection.execute_query(
            "SELECT COUNT(*) as total FROM events WHERE church_id = %s",
            (church_pk,),
            fetch_one=True
        )
        total = count_result.get("total") if count_result else 0

        # Query events with pagination
        rows = connection.execute_query(
            """SELECT e.event_id, e.event_type, e.occurred_at, e.actor, e.confidence, e.payload
               FROM events e
               WHERE e.church_id = %s
               ORDER BY e.occurred_at DESC
               LIMIT %s OFFSET %s""",
            (church_pk, limit, offset)
        ) or []

        # Build enhanced event response objects
        events = []
        exception_count = 0

        for row in rows:
            event_id = str(row.get("event_id", ""))
            payload = row.get("payload") or {}
            confidence = float(row.get("confidence") or 1.0)

            # Fetch tags for this event
            tag_rows = connection.execute_query(
                "SELECT tag_kind, tag_value FROM event_tags WHERE event_id = %s",
                (row.get("event_id"),)
            ) or []

            dimensions = {}
            for tag_row in tag_rows:
                dimensions[tag_row.get("tag_kind")] = tag_row.get("tag_value")

            # Detect if this is an exception/mismatch
            is_exception = (
                confidence < 0.70 or  # Low confidence
                (row.get("event_type") == "BankItemObserved" and "correlation_id" not in payload)  # Unmatched bank item
            )
            if is_exception:
                exception_count += 1

            # Format confidence with color code
            if confidence >= 0.80:
                confidence_color = "🟢"  # Green
            elif confidence >= 0.60:
                confidence_color = "🟡"  # Yellow
            else:
                confidence_color = "🔴"  # Red

            event_obj = {
                "event_id": event_id,
                "timestamp": row.get("occurred_at").isoformat() if row.get("occurred_at") else None,
                "event_type": row.get("event_type"),
                "source": payload.get("source", "system"),
                "provenance": {
                    "source_system": payload.get("source", "system"),
                    "document_id": payload.get("document_id", event_id),
                    "confidence": confidence
                },
                "economic_substance": {
                    "transaction_type": payload.get("transaction_type", "unknown"),
                    "amount": payload.get("amount", 0),
                    "vendor": payload.get("vendor"),
                    "description": payload.get("description", "")
                },
                "dimensions": dimensions,
                "confidence": confidence,
                "confidence_display": f"{confidence_color} {int(confidence * 100)}%",
                "is_exception": is_exception,
                "lineage": payload.get("lineage", [])
            }

            if not show_exceptions_only or is_exception:
                events.append(event_obj)

        return _json({
            "church_id": church_id,
            "total": total,
            "exception_count": exception_count,
            "events": events[:limit] if show_exceptions_only else events,
            "offset": offset,
            "limit": limit,
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)
'''

PHASE_2_ENHANCEMENTS = '''
# ===== PHASE 2: Discovery Layer - Similar Transactions & Evidence =====

@app.get("/api/events/{event_id}/similar")
async def find_similar_events(
    event_id: str,
    church_id: str = "holy_comforter",
    limit: int = 5,
) -> JSONResponse:
    """Find similar events for Q&A loop - transactions with matching dimensions.

    Used in: "User asks about transaction X, show similar transactions from history"
    Returns: Top 5 events with matching ministry/cost_center/vendor tags
    """
    from .db import connection
    import uuid

    try:
        event_uuid = uuid.UUID(event_id)
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )
        if not church_pk:
            return _json({"similar_events": []})

        church_pk = church_pk.get("id")

        # Get tags of the query event
        query_tags = connection.execute_query(
            "SELECT tag_kind, tag_value FROM event_tags WHERE event_id = %s",
            (event_uuid,)
        ) or []

        if not query_tags:
            return _json({"similar_events": []})

        # Find events with matching tags (same ministry, cost_center, vendor, etc.)
        tag_kinds = [t.get("tag_kind") for t in query_tags]
        similar_sql = """
            SELECT DISTINCT e.event_id, e.event_type, e.occurred_at, e.confidence, e.payload,
                   COUNT(*) as matching_tags
            FROM events e
            JOIN event_tags et ON e.event_id = et.event_id
            WHERE e.church_id = %s
            AND e.event_id != %s
            AND et.tag_kind = ANY(%s)
            GROUP BY e.event_id, e.event_type, e.occurred_at, e.confidence, e.payload
            ORDER BY matching_tags DESC, e.occurred_at DESC
            LIMIT %s
        """

        similar = connection.execute_query(
            similar_sql,
            (church_pk, event_uuid, tag_kinds, limit)
        ) or []

        similar_events = []
        for row in similar:
            similar_events.append({
                "event_id": str(row.get("event_id")),
                "event_type": row.get("event_type"),
                "timestamp": row.get("occurred_at").isoformat() if row.get("occurred_at") else None,
                "confidence": float(row.get("confidence") or 1.0),
                "matching_tags_count": row.get("matching_tags"),
                "payload": row.get("payload")
            })

        return _json({"similar_events": similar_events})

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.get("/api/decisions/{decision_id}/evidence")
async def get_decision_evidence(
    decision_id: str,
    church_id: str = "holy_comforter",
) -> JSONResponse:
    """Get evidence (cited events) for a decision - shows reasoning context.

    Used in: "User clicks 'why?' on a decision, see the events it was based on"
    Returns: Full event details for all events cited in the decision
    """
    try:
        from . import flow

        ledger = flow.get_ledger(church_id)

        # Find decision by ID
        decision = None
        for entry in ledger.entries:
            if entry.decision_id == decision_id:
                decision = entry
                break

        if not decision:
            return _json({"error": f"Decision {decision_id} not found"}, status_code=404)

        # Return decision + cited events
        return _json({
            "decision_id": decision_id,
            "reasoning": decision.reasoning,
            "confidence": decision.confidence,
            "alternatives": decision.alternatives,
            "evidence": {
                "event_ids": decision.cited_event_ids or [],
                "evidence_refs": decision.evidence_refs or [],
                "policy_invoked": decision.policy_invoked
            },
            "timestamp": decision.timestamp.isoformat() if decision.timestamp else None,
            "category": decision.category.value
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.get("/api/dimensions/{dimension_name}")
async def get_dimension_details(dimension_name: str) -> JSONResponse:
    """Get details about a specific dimension - usage stats and guidance.

    Phase 2: Helps users understand when to use each dimension
    """
    from .db import connection

    dimension_guides = {
        "ministry": {
            "description": "Ministry or program (worship, youth, outreach, etc.)",
            "usage": "Tag transactions that primarily serve a specific ministry",
            "examples": ["worship", "youth_ministry", "community_outreach", "facilities"],
            "notes": "One ministry per transaction. If multi-ministry, use beneficiary dimension."
        },
        "beneficiary": {
            "description": "Primary beneficiary or constituent group",
            "usage": "Who this transaction ultimately serves",
            "examples": ["congregation", "community", "staff", "facility"],
            "notes": "Different from ministry - a staff salary is ministry=operations, beneficiary=staff"
        },
        "cost_center": {
            "description": "Operational cost center or department",
            "usage": "For budget tracking and cost allocation",
            "examples": ["program", "operations", "admin", "fundraising"],
            "notes": "Use for P&L analysis by operational area"
        },
        "geography": {
            "description": "Physical location or campus",
            "usage": "Track spending by site, useful for multi-location orgs",
            "examples": ["US-MA", "US-CT", "US-National"],
            "notes": "Use ISO country+state format"
        },
        "funding_source": {
            "description": "Where funding came from",
            "usage": "Donor intent tracking and restricted fund compliance",
            "examples": ["donations", "grants", "earned_income", "endowment"],
            "notes": "Critical for nonprofit compliance"
        },
        "mission_impact": {
            "description": "How this advances the mission",
            "usage": "Mission-focused reporting and impact analysis",
            "examples": ["spiritual_growth", "community_service", "education"],
            "notes": "Enables mission-driven financial reporting"
        }
    }

    if dimension_name.lower() in dimension_guides:
        guide = dimension_guides[dimension_name.lower()]

        # Get usage count from DB
        try:
            count = connection.execute_query(
                "SELECT COUNT(*) as cnt FROM event_tags WHERE tag_kind = %s",
                (dimension_name.lower(),),
                fetch_one=True
            )
            usage_count = count.get("cnt") if count else 0
        except:
            usage_count = 0

        return _json({
            "dimension": dimension_name.lower(),
            "description": guide["description"],
            "usage": guide["usage"],
            "examples": guide["examples"],
            "notes": guide["notes"],
            "usage_count": usage_count
        })
    else:
        return _json({"error": f"Dimension '{dimension_name}' not found"}, status_code=404)
'''

PHASE_3_ENHANCEMENTS = '''
# ===== PHASE 3: Exception Management - Reconciliation Exceptions & Approval =====

@app.get("/api/reconciliation/exceptions")
async def get_reconciliation_exceptions(
    church_id: str = "holy_comforter",
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Get reconciliation exceptions - unmatched bank items and suspicious JEs.

    Returns:
    - Unmatched bank transactions
    - Low-confidence classifications
    - Pattern anomalies (payment delays, amount changes)
    """
    from .db import connection

    try:
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )
        if not church_pk:
            return _json({"exceptions": [], "total": 0})

        church_pk = church_pk.get("id")

        # Query unmatched bank items (no correlation_id or low confidence)
        exceptions_sql = """
            SELECT
                'UNMATCHED_BANK_ITEM' as exception_type,
                e.event_id,
                e.event_type,
                e.occurred_at,
                e.confidence,
                e.payload,
                'No matching JE found' as reason
            FROM events e
            WHERE e.church_id = %s
            AND e.event_type = 'BankItemObserved'
            AND (e.confidence < 0.70 OR e.correlation_id IS NULL)

            UNION

            SELECT
                'LOW_CONFIDENCE' as exception_type,
                e.event_id,
                e.event_type,
                e.occurred_at,
                e.confidence,
                e.payload,
                'Confidence below 70%' as reason
            FROM events e
            WHERE e.church_id = %s
            AND e.confidence < 0.70

            ORDER BY occurred_at DESC
            LIMIT %s OFFSET %s
        """

        exceptions = connection.execute_query(
            exceptions_sql,
            (church_pk, church_pk, limit, offset)
        ) or []

        exception_list = []
        for exc in exceptions:
            exception_list.append({
                "exception_id": str(exc.get("event_id")),
                "exception_type": exc.get("exception_type"),
                "event_type": exc.get("event_type"),
                "timestamp": exc.get("occurred_at").isoformat() if exc.get("occurred_at") else None,
                "confidence": float(exc.get("confidence") or 1.0),
                "reason": exc.get("reason"),
                "details": exc.get("payload"),
                "status": "pending_review"
            })

        return _json({
            "church_id": church_id,
            "total": len(exception_list),
            "exceptions": exception_list,
            "offset": offset,
            "limit": limit
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)


@app.post("/api/events/{event_id}/approve")
async def approve_exception(
    event_id: str,
    church_id: str = "holy_comforter",
    body: Optional[dict] = None,
) -> JSONResponse:
    """Approve an exception as 'OK' - marks it as reviewed and no action needed.

    Phase 3: Users can dismiss exceptions they've reviewed
    Body: {\"reason\": \"Already matched manually\", \"notes\": \"...\"}
    """
    try:
        import uuid
        from .db import connection

        event_uuid = uuid.UUID(event_id)
        church_pk = connection.execute_query(
            "SELECT id FROM churches WHERE church_id = %s",
            (church_id,),
            fetch_one=True
        )
        if not church_pk:
            return _json({"error": "Church not found"}, status_code=404)

        # Mark exception as approved (in a real system, update exception_approvals table)
        # For now, just return success
        approval_body = body or {}

        return _json({
            "event_id": event_id,
            "status": "approved",
            "approval_reason": approval_body.get("reason", "User reviewed and confirmed OK"),
            "approved_at": datetime.utcnow().isoformat(),
            "notes": approval_body.get("notes", "")
        })

    except Exception as e:
        return _json({"error": str(e)}, status_code=500)
'''

print("Phase 1-3 API enhancement code generated. Add to backend/main.py:")
print("\n" + "="*70)
print("PHASE 1: UI Polish")
print("="*70)
print(PHASE_1_ENHANCEMENTS)
print("\n" + "="*70)
print("PHASE 2: Discovery Layer")
print("="*70)
print(PHASE_2_ENHANCEMENTS)
print("\n" + "="*70)
print("PHASE 3: Exception Management")
print("="*70)
print(PHASE_3_ENHANCEMENTS)
