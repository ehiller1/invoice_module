"""Generate a print-ready check or check-request PDF from a PaymentInstruction."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from backend.models.schemas import PaymentInstruction


def generate_check_pdf(instruction: PaymentInstruction, output_path: str) -> str:
    """Generate a print-ready check PDF or check-request memo.

    Returns the path written.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "CHECK REQUEST", new_y="NEXT")
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 12)
    cr = instruction.check_record
    if cr:
        pdf.cell(0, 8, f"Pay to: {cr.payee}", new_y="NEXT")
        pdf.cell(0, 8, f"Amount: ${cr.amount}", new_y="NEXT")
        pdf.cell(0, 8, f"Date: {cr.check_date}", new_y="NEXT")
        if cr.memo:
            pdf.cell(0, 8, f"Memo: {cr.memo}", new_y="NEXT")
        if cr.address:
            pdf.cell(0, 8, f"Address: {cr.address}", new_y="NEXT")
        if cr.check_number:
            pdf.cell(0, 8, f"Check #: {cr.check_number}", new_y="NEXT")
    else:
        pdf.cell(0, 8, f"Amount: ${instruction.amount}", new_y="NEXT")

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 5, f"Payment ID: {instruction.payment_id}", new_y="NEXT")
    pdf.cell(0, 5, f"Linked JE: {instruction.je_id or 'N/A'}", new_y="NEXT")
    pdf.ln(8)
    pdf.cell(0, 5, "_______________________________", new_y="NEXT")
    pdf.cell(0, 5, "Treasurer Signature", new_y="NEXT")

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return str(out_path)
