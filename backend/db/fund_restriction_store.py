"""Store for fund restrictions with soft/hard distinction (Flow 6 - fund blocks)."""
from typing import Optional, Dict, Any, List, cast
from datetime import date as date_type
from .connection import execute_query


def create_fund_restriction(
    church_id: str,
    fund_id: str,
    restriction_type: str,  # 'SOFT' or 'HARD'
    restriction_reason: str,
    override_role: Optional[str] = None,
    effective_date: Optional[str] = None,
    expiration_date: Optional[str] = None,
) -> None:
    """Create a fund restriction (SOFT=donor preference, HARD=legal)."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        raise ValueError(f"Church {church_id} not found")

    fund_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM funds WHERE church_id = %s AND fund_id = %s",
        (church_row['id'], fund_id),
        fetch_one=True
    ))
    if not fund_row:
        raise ValueError(f"Fund {fund_id} not found for church {church_id}")

    execute_query(
        """INSERT INTO fund_restrictions
           (church_id, fund_id, restriction_type, restriction_reason, override_role, effective_date, expiration_date, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())""",
        (church_row['id'], fund_row['id'], restriction_type, restriction_reason, override_role, effective_date, expiration_date)
    )


def get_fund_restrictions(
    church_id: str,
    fund_id: str,
) -> List[Dict[str, Any]]:
    """Get all active restrictions for a fund."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        return []

    fund_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM funds WHERE church_id = %s AND fund_id = %s",
        (church_row['id'], fund_id),
        fetch_one=True
    ))
    if not fund_row:
        return []

    rows = cast(List[Dict[str, Any]], execute_query(
        """SELECT restriction_id, restriction_type, restriction_reason, override_role, effective_date, expiration_date
           FROM fund_restrictions
           WHERE church_id = %s AND fund_id = %s
           AND (effective_date IS NULL OR effective_date <= CURRENT_DATE)
           AND (expiration_date IS NULL OR expiration_date >= CURRENT_DATE)""",
        (church_row['id'], fund_row['id'])
    ))

    return rows if rows else []


def check_restriction_violation(
    church_id: str,
    fund_id: str,
    actor_role: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Check if posting to a fund violates restrictions.
    Returns: {violation: bool, type: 'SOFT'|'HARD'|None, reason: str, override_role: str|None}
    """
    restrictions = get_fund_restrictions(church_id, fund_id)

    for restriction in restrictions:
        restriction_type = restriction.get('restriction_type', 'HARD')
        reason = restriction.get('restriction_reason', '')
        override_role = restriction.get('override_role')

        if restriction_type == 'HARD':
            # Hard blocks always violate
            return {
                "violation": True,
                "type": "HARD",
                "reason": reason,
                "override_role": None,  # No override for hard blocks
            }
        elif restriction_type == 'SOFT':
            # Soft blocks only violate if actor role doesn't match override_role
            if actor_role and override_role and actor_role == override_role:
                # Actor can override
                continue
            else:
                # Actor cannot override or no override_role defined
                return {
                    "violation": True,
                    "type": "SOFT",
                    "reason": reason,
                    "override_role": override_role,
                }

    # No violations
    return {
        "violation": False,
        "type": None,
        "reason": "",
        "override_role": None,
    }
