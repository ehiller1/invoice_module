"""policy_votes table — indexed vote storage for policy cards.

Replaces the O(N) CardStore scan that previously merged votes into policy
listings. Each (policy_id, voter_id) is unique: voting again upserts the row.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .connection import execute_query

_ENSURED = False


def _ensure_table() -> None:
    """Create the policy_votes table on first use (idempotent)."""
    global _ENSURED
    if _ENSURED:
        return
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS policy_votes (
            id          SERIAL PRIMARY KEY,
            policy_id   VARCHAR(100) NOT NULL,
            voter_id    VARCHAR(100) NOT NULL,
            voter_role  VARCHAR(64),
            church_id   VARCHAR(100) NOT NULL,
            vote        VARCHAR(16)  NOT NULL,
            rationale   TEXT,
            cast_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (policy_id, voter_id)
        );
        """
    )
    execute_query(
        "CREATE INDEX IF NOT EXISTS idx_policy_votes_policy ON policy_votes(policy_id);"
    )
    execute_query(
        "CREATE INDEX IF NOT EXISTS idx_policy_votes_church ON policy_votes(church_id);"
    )
    _ENSURED = True


def record_vote(
    policy_id: str,
    voter_id: str,
    vote: str,
    *,
    church_id: str,
    voter_role: Optional[str] = None,
    rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert one vote. Returns the stored row."""
    _ensure_table()
    execute_query(
        """
        INSERT INTO policy_votes (policy_id, voter_id, voter_role, church_id, vote, rationale)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (policy_id, voter_id) DO UPDATE
            SET vote = EXCLUDED.vote,
                voter_role = COALESCE(EXCLUDED.voter_role, policy_votes.voter_role),
                rationale = EXCLUDED.rationale,
                cast_at = CURRENT_TIMESTAMP
        """,
        (policy_id, voter_id, voter_role, church_id, vote, rationale),
    )
    row = execute_query(
        "SELECT policy_id, voter_id, voter_role, church_id, vote, rationale, cast_at "
        "FROM policy_votes WHERE policy_id=%s AND voter_id=%s",
        (policy_id, voter_id),
        fetch_one=True,
    )
    return dict(row) if row else {}


def votes_for_policies(policy_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Return {policy_id: [vote_row, ...]} for the given policies in one query."""
    _ensure_table()
    if not policy_ids:
        return {}
    rows = execute_query(
        "SELECT policy_id, voter_id, voter_role, vote, rationale, cast_at "
        "FROM policy_votes WHERE policy_id = ANY(%s) "
        "ORDER BY cast_at DESC",
        (list(policy_ids),),
    ) or []
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r["policy_id"], []).append(dict(r))
    return out


def tally(policy_id: str) -> Dict[str, int]:
    """Return {yes, no, abstain, total} for a single policy."""
    _ensure_table()
    rows = execute_query(
        "SELECT vote, COUNT(*) AS n FROM policy_votes WHERE policy_id=%s GROUP BY vote",
        (policy_id,),
    ) or []
    out = {"yes": 0, "no": 0, "abstain": 0, "total": 0}
    for r in rows:
        v = (r.get("vote") or "").lower()
        n = int(r.get("n") or 0)
        if v in ("yes", "approve"):
            out["yes"] += n
        elif v in ("no", "reject"):
            out["no"] += n
        elif v == "abstain":
            out["abstain"] += n
        out["total"] += n
    return out
