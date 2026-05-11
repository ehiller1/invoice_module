"""Phase 18: Accrual & Amortization Engine."""
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, Any, List

from backend.cards.ids import validate_id_component
from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


def _add_months(dt: date, months: int) -> date:
    """Add a number of months to a date, clamping to valid day."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    days_in_month = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, days_in_month[month - 1])
    return dt.replace(year=year, month=month, day=day)


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
    validate_id_component(schedule_id, field="schedule_id")
    card_store = get_card_store()

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
    }

    card = MemoryCard(
        card_id=f"schedule-{schedule_id}",
        principal="accrual-engine",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Accrual: {description}",
        confidence=0.95,
        metadata=schedule_data,
    )
    card_store.write(card, chain=True)

    return schedule_data


async def project_accrual_entries(
    schedule_id: str,
) -> List[Dict[str, Any]]:
    """Project accrual/amortization journal entries from a stored schedule."""
    card_store = get_card_store()

    card = card_store.read(f"schedule-{schedule_id}")
    if not card:
        return []

    metadata = card.get("metadata", {})
    period_count = metadata.get("period_count", 0)
    periodic_amount = metadata.get("periodic_amount", 0.0)
    period_type = metadata.get("period_type", "monthly")
    start_date_str = metadata.get("start_date", "")
    expense_account = metadata.get("expense_account", "")
    description = metadata.get("description", "Accrual")

    try:
        start = date.fromisoformat(start_date_str)
    except (ValueError, TypeError):
        logger.error("Invalid start_date '%s' for schedule %s", start_date_str, schedule_id)
        return []

    months_per_period = {"monthly": 1, "quarterly": 3, "annual": 12}.get(period_type, 1)

    entries = []
    for i in range(period_count):
        entry_date = _add_months(start, i * months_per_period)
        entries.append({
            "period": i + 1,
            "entry_date": entry_date.isoformat(),
            "account": expense_account,
            "amount": periodic_amount,
            "description": f"{description} — period {i + 1} of {period_count}",
        })

    return entries


async def record_audit_finding(
    finding_id: str,
    category: str,
    severity: str,
    description: str,
    affected_accounts: List[str],
) -> Dict[str, Any]:
    """Record an audit finding."""
    validate_id_component(finding_id, field="finding_id")
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
        principal="audit-engine",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Audit finding: {description}",
        confidence=0.90,
        metadata=finding_data,
    )
    card_store.write(card, chain=True)

    return finding_data


async def close_audit_finding(
    finding_id: str,
    remediation: str,
) -> Dict[str, Any]:
    """Close/resolve an audit finding."""
    validate_id_component(finding_id, field="finding_id")
    card_store = get_card_store()

    closed_at = datetime.utcnow().isoformat()

    resolution_card = MemoryCard(
        card_id=f"audit-{finding_id}-closed",
        principal="audit-engine",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Audit finding {finding_id} closed: {remediation}",
        confidence=0.95,
        metadata={
            "finding_id": finding_id,
            "status": "closed",
            "remediation": remediation,
            "closed_at": closed_at,
        },
    )
    card_store.write(resolution_card, chain=True)

    return {
        "finding_id": finding_id,
        "status": "closed",
        "remediation": remediation,
        "closed_at": closed_at,
    }
