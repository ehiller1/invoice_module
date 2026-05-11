"""Phase 16: Receipt Capture — OCR + GL Mapping.

Process receipt images and suggest GL mappings via OCR and vendor intelligence.
"""

import logging
from decimal import Decimal
from typing import Dict, Any, Optional, List

from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def process_receipt_image(
    image_data: bytes,
    file_name: str,
) -> Dict[str, Any]:
    """Process receipt image via OCR.

    Args:
        image_data: Binary image data (JPEG, PNG)
        file_name: Original file name for context

    Returns:
        Dict with:
        - extracted_text: OCR result
        - vendor_info: Extracted vendor details
        - line_items: Detected line items with amounts
        - confidence_score: OCR confidence (0.0-1.0)
    """
    # Placeholder: would call OCR service (AWS Textract, Google Vision, Azure, etc.)
    # For now, return a structure showing what would be extracted

    extracted = {
        "vendor_name": "Sample Vendor Inc",
        "vendor_address": "123 Main St, City, ST 12345",
        "invoice_number": "INV-2026-05001",
        "invoice_date": "2026-05-11",
        "total_amount": "1250.00",
        "line_items": [
            {
                "description": "Office Supplies",
                "quantity": 1,
                "unit_price": "750.00",
                "amount": "750.00",
            },
            {
                "description": "Shipping",
                "quantity": 1,
                "unit_price": "50.00",
                "amount": "50.00",
            },
            {
                "description": "Tax",
                "quantity": 1,
                "unit_price": "100.00",
                "amount": "100.00",
            },
        ],
    }

    return {
        "extracted_text": str(extracted),
        "vendor_info": {
            "name": extracted["vendor_name"],
            "address": extracted["vendor_address"],
        },
        "line_items": extracted["line_items"],
        "confidence_score": 0.92,
        "raw_confidence": {"overall": 0.92, "vendor": 0.95, "amounts": 0.89},
    }


async def extract_vendor_info(
    vendor_name: str,
    address: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract or lookup vendor information.

    Args:
        vendor_name: Vendor name from receipt
        address: Optional vendor address

    Returns:
        Dict with vendor hierarchy and matching
    """
    card_store = get_card_store()

    # Query vendor master (would be stored as MemoryCards)
    all_vendors = card_store.query_by_principal("intake-specialist")
    vendor_matches = [
        v for v in all_vendors
        if vendor_name.lower() in str(v.get("content", "")).lower()
    ]

    # Return vendor info with matching score
    match_score = 0.95 if vendor_matches else 0.60

    return {
        "vendor_name": vendor_name,
        "address": address,
        "matched": len(vendor_matches) > 0,
        "match_score": match_score,
        "vendor_id": _hash_vendor_name(vendor_name),
        "vendor_category": _infer_vendor_category(vendor_name),
        "default_expense_accounts": _get_default_accounts(vendor_name),
    }


async def suggest_gl_mapping(
    vendor_name: str,
    amount: Decimal,
    description: str,
    vendor_category: Optional[str] = None,
) -> Dict[str, Any]:
    """Suggest GL account mapping for receipt line item.

    Args:
        vendor_name: Vendor name
        amount: Transaction amount
        description: Line item description
        vendor_category: Optional vendor category

    Returns:
        Dict with suggested GL accounts and confidence
    """
    # Infer category if not provided
    if not vendor_category:
        vendor_category = _infer_vendor_category(vendor_name)

    # Map category to GL accounts
    suggested_accounts = _map_category_to_accounts(vendor_category, amount)

    # Score each suggestion
    scored = []
    for account, threshold in suggested_accounts:
        confidence = _calculate_mapping_confidence(
            vendor_name,
            description,
            vendor_category,
            account,
        )
        scored.append(
            {
                "account": account,
                "confidence": confidence,
                "description": _get_account_description(account),
                "is_restricted": _check_fund_restriction(account),
                "requires_approval": confidence < 0.75,
            }
        )

    # Sort by confidence
    scored.sort(key=lambda x: x["confidence"], reverse=True)

    return {
        "vendor_name": vendor_name,
        "amount": float(amount),
        "category": vendor_category,
        "suggestions": scored[:3],  # Top 3 suggestions
        "highest_confidence": scored[0]["confidence"] if scored else 0.0,
    }


# ===== Helper Functions =====


def _hash_vendor_name(vendor_name: str) -> str:
    """Create a vendor ID from name."""
    import hashlib
    return hashlib.md5(vendor_name.lower().encode()).hexdigest()[:12]


def _infer_vendor_category(vendor_name: str) -> str:
    """Infer vendor category from name."""
    name_lower = vendor_name.lower()

    # Pattern matching for common vendor types
    patterns = {
        "supplies": ["staples", "office", "supplies", "depot", "amazon"],
        "utilities": ["electric", "gas", "water", "utility", "power"],
        "professional_services": ["consulting", "legal", "accounting", "audit"],
        "travel": ["uber", "airline", "hotel", "expedia", "booking"],
        "software": ["adobe", "microsoft", "salesforce", "slack", "zoom"],
        "facilities": ["cleaning", "maintenance", "janitorial", "property"],
    }

    for category, keywords in patterns.items():
        if any(keyword in name_lower for keyword in keywords):
            return category

    return "other"


def _get_default_accounts(vendor_name: str) -> List[str]:
    """Get default GL accounts for vendor category."""
    category = _infer_vendor_category(vendor_name)

    defaults = {
        "supplies": ["51100", "51200"],
        "utilities": ["61000", "61100"],
        "professional_services": ["51300", "51400"],
        "travel": ["52000", "52100"],
        "software": ["61200", "61300"],
        "facilities": ["52500"],
        "other": ["59999"],
    }

    return defaults.get(category, ["59999"])


def _map_category_to_accounts(
    category: str,
    amount: Decimal,
) -> List[tuple[str, Decimal]]:
    """Map expense category to GL accounts with thresholds."""
    mappings = {
        "supplies": [("51100", Decimal("5000")), ("51200", Decimal("0"))],
        "utilities": [("61000", Decimal("0"))],
        "professional_services": [("51300", Decimal("0")), ("51400", Decimal("0"))],
        "travel": [("52000", Decimal("0")), ("52100", Decimal("0"))],
        "software": [("61200", Decimal("0")), ("61300", Decimal("0"))],
        "facilities": [("52500", Decimal("0"))],
        "other": [("59999", Decimal("0"))],
    }

    return mappings.get(category, [("59999", Decimal("0"))])


def _calculate_mapping_confidence(
    vendor_name: str,
    description: str,
    category: str,
    account: str,
) -> float:
    """Calculate confidence score for GL mapping."""
    # Start with base confidence
    confidence = 0.60

    # Boost if vendor name appears in description
    if vendor_name.lower() in description.lower():
        confidence += 0.10

    # Boost if category matches account
    if category != "other":
        confidence += 0.15

    # Adjust based on account specificity
    if account.endswith("00"):
        confidence += 0.10  # Parent accounts less specific

    # Cap at 0.99
    return min(confidence, 0.99)


def _get_account_description(account: str) -> str:
    """Get human-readable account description."""
    descriptions = {
        "51100": "Office Supplies",
        "51200": "Professional Services",
        "51300": "Consulting & Professional Fees",
        "51400": "Legal & Accounting",
        "52000": "Travel & Transportation",
        "52100": "Meals & Entertainment",
        "52500": "Facilities & Maintenance",
        "61000": "Utilities",
        "61100": "Communications",
        "61200": "Software & Subscriptions",
        "61300": "IT Services",
        "59999": "Miscellaneous",
    }

    return descriptions.get(account, f"Account {account}")


def _check_fund_restriction(account: str) -> bool:
    """Check if account has fund restrictions."""
    # Placeholder: would query policy rules from Card Store
    restricted = ["52000", "52100"]  # Travel accounts may be restricted
    return account in restricted
