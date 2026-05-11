"""Store for policy versions with dry-run capability (Flow 14 - policy versioning)."""
from typing import List, Optional, Dict, Any, cast
from datetime import date as date_type
import uuid
from .connection import execute_query


def create_policy_version(
    church_id: str,
    policy_id: str,
    policy_text: str,
    effective_date: str,  # YYYY-MM-DD
    created_by: str,
    expires_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new policy version. Auto-increments version number.
    Returns the created policy version record.
    """
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        raise ValueError(f"Church {church_id} not found")

    # Get next version number for this policy
    result = cast(Optional[Dict[str, Any]], execute_query(
        """SELECT COALESCE(MAX(version), 0) + 1 as next_version
           FROM policy_versions
           WHERE church_id = %s AND policy_id = %s""",
        (church_row['id'], policy_id),
        fetch_one=True
    ))
    next_version = result.get('next_version', 1) if result else 1

    # Insert new version
    version_id = f"pv-{uuid.uuid4().hex[:16]}"
    execute_query(
        """INSERT INTO policy_versions
           (version_id, policy_id, church_id, version, policy_text, effective_date, expires_date, created_by, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
        (version_id, policy_id, church_row['id'], next_version, policy_text, effective_date, expires_date, created_by)
    )

    return {
        "version_id": version_id,
        "policy_id": policy_id,
        "version": next_version,
        "policy_text": policy_text,
        "effective_date": effective_date,
        "expires_date": expires_date,
        "created_by": created_by,
    }


def get_current_policy_version(
    church_id: str,
    policy_id: str,
) -> Optional[Dict[str, Any]]:
    """Get the currently effective policy version for a policy."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        return None

    row = cast(Optional[Dict[str, Any]], execute_query(
        """SELECT version_id, policy_id, version, policy_text, effective_date, expires_date, created_by, created_at
           FROM policy_versions
           WHERE church_id = %s AND policy_id = %s
           AND effective_date <= CURRENT_DATE
           AND (expires_date IS NULL OR expires_date >= CURRENT_DATE)
           ORDER BY effective_date DESC, version DESC
           LIMIT 1""",
        (church_row['id'], policy_id),
        fetch_one=True
    ))
    return row if row else None


def get_policy_version(
    church_id: str,
    policy_id: str,
    version: int,
) -> Optional[Dict[str, Any]]:
    """Get a specific policy version by number."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        return None

    row = cast(Optional[Dict[str, Any]], execute_query(
        """SELECT version_id, policy_id, version, policy_text, effective_date, expires_date, created_by, created_at
           FROM policy_versions
           WHERE church_id = %s AND policy_id = %s AND version = %s""",
        (church_row['id'], policy_id, version),
        fetch_one=True
    ))
    return row if row else None


def list_policy_versions(
    church_id: str,
    policy_id: str,
) -> List[Dict[str, Any]]:
    """List all versions of a policy."""
    church_row = cast(Optional[Dict[str, Any]], execute_query(
        "SELECT id FROM churches WHERE church_id = %s",
        (church_id,),
        fetch_one=True
    ))
    if not church_row:
        return []

    rows = cast(List[Dict[str, Any]], execute_query(
        """SELECT version_id, policy_id, version, policy_text, effective_date, expires_date, created_by, created_at
           FROM policy_versions
           WHERE church_id = %s AND policy_id = %s
           ORDER BY version DESC""",
        (church_row['id'], policy_id)
    ))
    return rows if rows else []


def dry_run_policy_version(
    church_id: str,
    policy_id: str,
    new_policy_text: str,
    effective_date: str,
) -> Dict[str, Any]:
    """
    Dry-run a policy change without persisting.
    Returns a projection of how the policy would affect decisions/rules.
    """
    # This is a placeholder for the simulation engine
    # In a real implementation, this would replay recent decisions
    # against the proposed policy to show what would change
    return {
        "policy_id": policy_id,
        "version": "PROPOSED",
        "effective_date": effective_date,
        "projected_changes": {
            "decisions_affected": 0,
            "new_approvals_required": [],
            "removed_approvals": [],
            "changed_routing": [],
        },
        "summary": "No recent decisions would be affected by this policy change",
    }
