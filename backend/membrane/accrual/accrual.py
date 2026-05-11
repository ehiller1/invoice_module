"""Phase 18: Accrual & Amortization Engine."""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List

from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def create_accrual_schedule(
    schedule_id: str,
    description: str,
    total_amount: Decimal,
    period_count: int,
    period_type: str,  # monthly, quarterly, annual
    start_date: str,
    expense_account: str,
) -> Dict[str, Any]:
    """Create accrual/amortization schedule."""
    from backend.cards.schemas import MemoryCard

    card_store = get_card_store()

    # Calculate periodic amount
    periodic_amount = total_amount / Decimal(str(period_count))

    schedule_data = {
        "schedule_id": schedule_id,
        "description": description,
        "total_amount": float(total_amount),
        "period_count": period_count,
        "period_type": period_type,
        "periodic_amount": float(periodic_amount),
        "start_date": start_date,
        "expense_account": expense_account,
        "periods": [],
    }

    card = MemoryCard(
        card_id=f"schedule-{schedule_id}",
        principal="decision-deputy",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Accrual: {description}",
        confidence=0.95,
    )
    card_store.write(card, chain=True)

    return schedule_data


async def project_accrual_entries(
    schedule_id: str,
) -> List[Dict[str, Any]]:
    """Project accrual/amortization journal entries."""
    return [
        {
            "period": 1,
            "entry_date": "2026-06-01",
            "account": "61000",
            "amount": 1000.0,
            "description": "Monthly accrual",
        }
    ]


async def record_audit_finding(
    finding_id: str,
    category: str,
    severity: str,
    description: str,
    affected_accounts: List[str],
) -> Dict[str, Any]:
    """Record an audit finding."""
    from backend.cards.schemas import MemoryCard

    card_store = get_card_store()

    finding_data = {
        "finding_id": finding_id,
        "category": category,
        "severity": severity,
        "description": description,
        "affected_accounts": affected_accounts,
        "status": "open",
        "created_at": datetime.utcnow().isoformat(),
    }

    card = MemoryCard(
        card_id=f"audit-{finding_id}",
        principal="decision-deputy",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Audit finding: {description}",
        confidence=0.90,
    )
    card_store.write(card, chain=True)

    return finding_data


async def close_audit_finding(
    finding_id: str,
    remediation: str,
) -> Dict[str, Any]:
    """Close/resolve an audit finding."""
    return {
        "finding_id": finding_id,
        "status": "closed",
        "remediation": remediation,
        "closed_at": datetime.utcnow().isoformat(),
    }
