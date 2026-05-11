"""Stores for exception, policy, question, and recommendation cards (HITL queues)."""
from typing import List, Optional, Dict, Any, Tuple, cast
from datetime import datetime
import uuid
import json
from .connection import execute_query


def create_exception_card(
    church_id: str,
    exception_type: str,
    title: str,
    description: str,
    evidence: Optional[Dict[str, Any]] = None,
    suggested_action: Optional[Dict[str, Any]] = None,
    job_id: Optional[str] = None,
    assigned_to: Optional[str] = None,
) -> str:
    """Create an exception card (HITL inbox item). Returns card_id."""
    card_id = f"exc-{uuid.uuid4().hex[:16]}"

    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        raise ValueError(f"Church {church_id} not found")

    execute_query(
        """INSERT INTO exception_cards
           (card_id, church_id, exception_type, title, description, evidence, suggested_action, job_id, assigned_to, status, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
        (
            card_id, church_row.get('id'), exception_type, title, description,
            json.dumps(evidence) if evidence else None,
            json.dumps(suggested_action) if suggested_action else None,
            job_id, assigned_to, "OPEN"
        )
    )
    return card_id


def list_exception_cards(church_id: str, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """List exception cards for a church. Returns (cards, total_count)."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        return [], 0

    # Get total count
    if status:
        total = cast(Optional[Dict[str, Any]], execute_query(
            "SELECT COUNT(*) as cnt FROM exception_cards WHERE church_id = %s AND status = %s",
            (church_row['id'], status),
            fetch_one=True
        ))
    else:
        total = cast(Optional[Dict[str, Any]], execute_query(
            "SELECT COUNT(*) as cnt FROM exception_cards WHERE church_id = %s",
            (church_row['id'],),
            fetch_one=True
        ))

    # Get paginated results
    if status:
        rows = cast(List[Dict[str, Any]], execute_query(
            """SELECT card_id, exception_type, title, description, evidence, suggested_action, job_id, assigned_to, status, created_at
               FROM exception_cards WHERE church_id = %s AND status = %s
               ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (church_row['id'], status, limit, offset)
        ))
    else:
        rows = cast(List[Dict[str, Any]], execute_query(
            """SELECT card_id, exception_type, title, description, evidence, suggested_action, job_id, assigned_to, status, created_at
               FROM exception_cards WHERE church_id = %s
               ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (church_row['id'], limit, offset)
        ))

    # Parse JSON fields
    for row in rows:
        if row.get('evidence'):
            if row.get('evidence') and isinstance(row['evidence'], str):
                row['evidence'] = json.loads(row['evidence'])
            if row.get('suggested_action') and isinstance(row['suggested_action'], str):
                row['suggested_action'] = json.loads(row['suggested_action'])

    return rows, total.get('cnt', 0) if total else 0


def resolve_exception_card(card_id: str, resolution: Optional[Dict[str, Any]] = None) -> None:
    """Mark an exception card as resolved."""
    execute_query(
        """UPDATE exception_cards SET status = %s, resolution_data = %s, resolved_at = NOW()
           WHERE card_id = %s""",
        ("RESOLVED", json.dumps(resolution) if resolution else None, card_id)
    )


def create_policy_card(
    church_id: str,
    policy_id: str,
    title: str,
    description: str,
    proposed_by: Optional[str] = None,
    requires_vote: bool = False,
) -> str:
    """Create a policy card (for policy approval/voting)."""
    card_id = f"pol-{uuid.uuid4().hex[:16]}"

    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        raise ValueError(f"Church {church_id} not found")

    execute_query(
        """INSERT INTO policy_cards
           (card_id, church_id, policy_id, title, description, proposed_by, requires_vote, status, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
        (card_id, church_row.get('id'), policy_id, title, description, proposed_by, requires_vote, "OPEN")
    )
    return card_id


def list_policy_cards(church_id: str, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """List policy cards for a church."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        return [], 0

    if status:
        total = cast(Optional[Dict[str, Any]], execute_query(
            "SELECT COUNT(*) as cnt FROM policy_cards WHERE church_id = %s AND status = %s",
            (church_row['id'], status),
            fetch_one=True
        ))
        rows = cast(List[Dict[str, Any]], execute_query(
            """SELECT card_id, policy_id, title, description, proposed_by, requires_vote, status, created_at, resolved_at, resolution_data
               FROM policy_cards WHERE church_id = %s AND status = %s
               ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (church_row['id'], status, limit, offset)
        ))
    else:
        total = cast(Optional[Dict[str, Any]], execute_query(
            "SELECT COUNT(*) as cnt FROM policy_cards WHERE church_id = %s",
            (church_row['id'],),
            fetch_one=True
        ))
        rows = cast(List[Dict[str, Any]], execute_query(
            """SELECT card_id, policy_id, title, description, proposed_by, requires_vote, status, created_at, resolved_at, resolution_data
               FROM policy_cards WHERE church_id = %s
               ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (church_row['id'], limit, offset)
        ))

    # Normalize output format to match exception_cards schema
    for row in rows:
        # Normalize evidence from resolution_data
        row['evidence'] = {}
        if row.get('resolution_data'):
            if isinstance(row['resolution_data'], str):
                row['evidence'] = json.loads(row['resolution_data'])
            else:
                row['evidence'] = row['resolution_data'] or {}
        row['exception_type'] = 'policy'  # For consistency
        row['assigned_to'] = row.get('proposed_by')  # Map proposed_by to assigned_to

    return rows, total.get('cnt', 0) if total else 0


def create_question_card(
    church_id: str,
    question_text: str,
    asked_by: Optional[str] = None,
    assigned_to: Optional[str] = None,
) -> str:
    """Create a question card (for Q&A queue)."""
    card_id = f"q-{uuid.uuid4().hex[:16]}"

    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        raise ValueError(f"Church {church_id} not found")

    execute_query(
        """INSERT INTO question_cards
           (card_id, church_id, question_text, asked_by, assigned_to, status, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
        (card_id, church_row.get('id'), question_text, asked_by, assigned_to, "OPEN")
    )
    return card_id


def list_question_cards(church_id: str, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """List question cards for a church."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        return [], 0

    if status:
        total = cast(Optional[Dict[str, Any]], execute_query(
            "SELECT COUNT(*) as cnt FROM question_cards WHERE church_id = %s AND status = %s",
            (church_row['id'], status),
            fetch_one=True
        ))
        rows = cast(List[Dict[str, Any]], execute_query(
            """SELECT card_id, question_text, asked_by, assigned_to, status, created_at, resolved_at, response_data
               FROM question_cards WHERE church_id = %s AND status = %s
               ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (church_row['id'], status, limit, offset)
        ))
    else:
        total = cast(Optional[Dict[str, Any]], execute_query(
            "SELECT COUNT(*) as cnt FROM question_cards WHERE church_id = %s",
            (church_row['id'],),
            fetch_one=True
        ))
        rows = cast(List[Dict[str, Any]], execute_query(
            """SELECT card_id, question_text, asked_by, assigned_to, status, created_at, resolved_at, response_data
               FROM question_cards WHERE church_id = %s
               ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (church_row['id'], limit, offset)
        ))

    # Normalize output format to match exception_cards schema
    for row in rows:
        # Map question_text to title
        row['title'] = row.get('question_text', '')
        row['description'] = ''  # questions don't have descriptions
        # Normalize evidence from response_data
        row['evidence'] = {}
        if row.get('response_data'):
            if isinstance(row['response_data'], str):
                row['evidence'] = json.loads(row['response_data'])
            else:
                row['evidence'] = row['response_data'] or {}
        row['exception_type'] = 'question'  # For consistency

    return rows, total.get('cnt', 0) if total else 0


def create_recommendation_card(
    church_id: str,
    recommendation_type: str,
    title: str,
    description: str,
    impact_score: float = 0.5,
    confidence_pct: float = 0.8,
) -> str:
    """Create a recommendation card."""
    card_id = f"rec-{uuid.uuid4().hex[:16]}"

    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        raise ValueError(f"Church {church_id} not found")

    execute_query(
        """INSERT INTO recommendation_cards
           (card_id, church_id, recommendation_type, title, description, impact_score, confidence_pct, status, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
        (card_id, church_row.get('id'), recommendation_type, title, description, impact_score, confidence_pct, "OPEN")
    )
    return card_id


def list_recommendation_cards(church_id: str, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """List recommendation cards for a church."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        return [], 0

    if status:
        total = cast(Optional[Dict[str, Any]], execute_query(
            "SELECT COUNT(*) as cnt FROM recommendation_cards WHERE church_id = %s AND status = %s",
            (church_row['id'], status),
            fetch_one=True
        ))
        rows = cast(List[Dict[str, Any]], execute_query(
            """SELECT card_id, recommendation_type, title, description, impact_score, confidence_pct, status, created_at, decided_at, decision_data
               FROM recommendation_cards WHERE church_id = %s AND status = %s
               ORDER BY impact_score DESC LIMIT %s OFFSET %s""",
            (church_row['id'], status, limit, offset)
        ))
    else:
        total = cast(Optional[Dict[str, Any]], execute_query(
            "SELECT COUNT(*) as cnt FROM recommendation_cards WHERE church_id = %s",
            (church_row['id'],),
            fetch_one=True
        ))
        rows = cast(List[Dict[str, Any]], execute_query(
            """SELECT card_id, recommendation_type, title, description, impact_score, confidence_pct, status, created_at, decided_at, decision_data
               FROM recommendation_cards WHERE church_id = %s
               ORDER BY impact_score DESC LIMIT %s OFFSET %s""",
            (church_row['id'], limit, offset)
        ))

    # Normalize output format to match exception_cards schema
    for row in rows:
        # Normalize evidence from decision_data
        row['evidence'] = {}
        if row.get('decision_data'):
            if isinstance(row['decision_data'], str):
                row['evidence'] = json.loads(row['decision_data'])
            else:
                row['evidence'] = row['decision_data'] or {}
        row['exception_type'] = 'recommendation'  # For consistency
        row['resolved_at'] = row.get('decided_at')  # Map decided_at to resolved_at

    return rows, total.get('cnt', 0) if total else 0
