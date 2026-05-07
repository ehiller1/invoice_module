"""FR-08.4: Credit-card memo generator (instruction-only — no auto-charge)."""
from __future__ import annotations

from backend.models.schemas import PaymentInstruction


def generate_cc_memo(instruction: PaymentInstruction) -> str:
    """Return a human-executable instruction text for a CREDIT_CARD payment.

    The memo describes what a treasurer should do — EIME never auto-charges.
    """
    cc = instruction.cc_memo
    amt = instruction.amount
    vendor = cc.vendor_name if cc else "vendor"
    desc = (cc.description if cc else "") or ""
    last4 = (cc.card_last4 if cc else None) or "XXXX"
    je_id = instruction.je_id or "(no JE)"
    return (
        f"CREDIT CARD INSTRUCTION\n"
        f"========================\n"
        f"Payment ID: {instruction.payment_id}\n"
        f"JE: {je_id}\n"
        f"Vendor:  {vendor}\n"
        f"Amount:  ${amt}\n"
        f"Card:    ****{last4}\n"
        f"Memo:    {desc}\n\n"
        f"ACTION: Manually charge ${amt} to organization credit card "
        f"({last4}) for {vendor}. Save receipt and reconcile when statement "
        f"arrives. EIME does NOT auto-charge."
    )
