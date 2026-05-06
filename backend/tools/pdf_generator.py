"""PDF audit trail generator using fpdf2."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from fpdf import FPDF, XPos, YPos

NAVY = (15, 31, 61)
GOLD = (201, 162, 39)
SLATE = (100, 116, 139)
WHITE = (255, 255, 255)
LIGHT = (248, 250, 252)
GREEN = (22, 163, 74)
RED = (220, 38, 38)
AMBER = (217, 119, 6)


class AuditPDF(FPDF):
    def __init__(self, church_name: str) -> None:
        super().__init__()
        self.church_name = church_name
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self) -> None:
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 210, 14, "F")
        self.set_y(3)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*WHITE)
        self.cell(0, 8, f"EIME — {self.church_name}  |  Invoice Audit Trail", align="L")
        self.set_text_color(0, 0, 0)
        self.ln(12)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*SLATE)
        self.cell(0, 5, f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  |  Page {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)

    def section_title(self, title: str) -> None:
        self.set_fill_color(*LIGHT)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(0, 7, f"  {title}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def kv_row(self, label: str, value: str, bold_value: bool = False) -> None:
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*SLATE)
        self.cell(45, 5, label)
        self.set_font("Helvetica", "B" if bold_value else "", 8)
        self.set_text_color(0, 0, 0)
        self.cell(0, 5, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def badge(self, text: str, color: tuple) -> None:
        self.set_font("Helvetica", "B", 7)
        self.set_fill_color(*color)
        self.set_text_color(*WHITE)
        w = self.get_string_width(text) + 5
        self.cell(w, 5, text, fill=True, border="0")
        self.set_text_color(0, 0, 0)
        self.set_fill_color(255, 255, 255)

    def risk_color(self, level: str) -> tuple:
        return {"LOW": GREEN, "MEDIUM": AMBER, "HIGH": (239, 68, 68), "CRITICAL": (127, 29, 29)}.get(level, SLATE)


def _fmt_money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return str(v)


def generate_audit_pdf(audit_data: Dict[str, Any], output_path: Path) -> Path:
    """Generate a complete audit trail PDF from the audit data dict."""
    invoice = audit_data.get("invoice") or {}
    classified = audit_data.get("classified") or []
    je = audit_data.get("journal_entry") or {}
    audit_log = audit_data.get("audit_log") or []
    risk = audit_data.get("risk_assessment") or {}
    fraud = audit_data.get("fraud_assessment") or {}

    church_name = je.get("church_id", "Church").replace("_", " ").title()
    pdf = AuditPDF(church_name)
    pdf.add_page()

    # ── Page 1: Invoice Summary ──────────────────────────────────────────────
    pdf.section_title("INVOICE SUMMARY")
    pdf.kv_row("Vendor:", invoice.get("vendor_name", "—"))
    pdf.kv_row("Vendor Address:", invoice.get("vendor_address") or "—")
    pdf.kv_row("Invoice Number:", invoice.get("invoice_number", "—"), bold_value=True)
    pdf.kv_row("Invoice Date:", str(invoice.get("invoice_date", "—")))
    pdf.kv_row("Due Date:", str(invoice.get("due_date") or "—"))
    pdf.kv_row("Document Type:", invoice.get("document_type", "—"))
    pdf.kv_row("Total Amount:", _fmt_money(invoice.get("total_amount", 0)), bold_value=True)
    pdf.kv_row("Tax Amount:", _fmt_money(invoice.get("tax_amount", 0)))
    pdf.kv_row("Memo:", invoice.get("memo") or "—")
    pdf.ln(3)

    if invoice.get("warnings"):
        pdf.section_title("EXTRACTION WARNINGS")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*AMBER)
        for w in invoice["warnings"]:
            pdf.cell(0, 5, f"  ⚠  {w}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    # ── Risk & Fraud Summary ──────────────────────────────────────────────
    pdf.section_title("RISK & FRAUD ASSESSMENT")
    if risk:
        rl = risk.get("risk_level", "—")
        rs = risk.get("risk_score", 0)
        rc = pdf.risk_color(rl)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(45, 5, "Misclassification Risk:")
        pdf.badge(f"{rl}  ({rs:.3f})", rc)
        pdf.ln(6)
        if risk.get("recommendations"):
            for rec in risk["recommendations"]:
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(*SLATE)
                pdf.cell(0, 4, f"  → {rec}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
        pdf.ln(1)

    if fraud:
        fl = fraud.get("fraud_level", "—")
        fs = fraud.get("fraud_score", 0)
        fc = pdf.risk_color(fl)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(45, 5, "Fraud Risk:")
        pdf.badge(f"{fl}  ({fs:.3f})", fc)
        pdf.ln(6)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(45, 5, "Recommended Action:")
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, fraud.get("recommended_action", "—"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        sigs = fraud.get("signals") or []
        if sigs:
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*SLATE)
            pdf.cell(0, 4, "  Fraud Signals Detected:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            for sig in sigs:
                pdf.set_font("Helvetica", "", 7)
                pdf.cell(5, 4, "")
                pdf.cell(15, 4, f"[Cat {sig['category']}]")
                pdf.cell(0, 4, f"{sig['signal_id']}: {sig['description'][:80]}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    # ── Page 2: Classification ───────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("CLASSIFICATION RESULTS")

    col_w = [10, 65, 35, 25, 18, 17]
    hdrs = ["#", "Description", "Category", "Ministry", "Amount", "Conf."]
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(*WHITE)
    for w, h in zip(col_w, hdrs):
        pdf.cell(w, 6, h, fill=True, border=0)
    pdf.ln(6)
    pdf.set_text_color(0, 0, 0)

    for i, cl in enumerate(classified):
        fill = i % 2 == 0
        pdf.set_fill_color(*LIGHT)
        pdf.set_font("Helvetica", "", 7)
        desc = str(cl.get("description", ""))[:40]
        cat = str(cl.get("expense_category", "")).replace("_", " ")[:20]
        ministry = str(cl.get("ministry_area") or "—")[:12]
        amt = _fmt_money(cl.get("amount", 0))
        conf = f"{float(cl.get('confidence', 0)):.0%}"
        vals = [str(i + 1), desc, cat, ministry, amt, conf]
        for w, v in zip(col_w, vals):
            pdf.cell(w, 5, v, fill=fill, border=0)
        pdf.ln(5)

        # Rationale
        rat = str(cl.get("classification_rationale", ""))[:100]
        if rat:
            pdf.set_font("Helvetica", "I", 6)
            pdf.set_text_color(*SLATE)
            pdf.cell(10, 4, "")
            pdf.cell(0, 4, f"↳ {rat}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)

        # Per-line risk
        if risk.get("per_line_risks"):
            lr_map = {lr["line_id"]: lr for lr in risk["per_line_risks"]}
            lr = lr_map.get(cl.get("line_id", ""))
            if lr and lr["risk_level"] != "LOW":
                rc = pdf.risk_color(lr["risk_level"])
                pdf.set_font("Helvetica", "", 6)
                pdf.cell(10, 4, "")
                pdf.set_text_color(*rc)
                flags = ", ".join(lr.get("flags", []))
                pdf.cell(0, 4, f"Risk: {lr['risk_level']} ({lr['risk_score']:.3f}) — {flags}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(0, 0, 0)

    pdf.ln(3)

    # ── Page 3: Journal Entry ────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("JOURNAL ENTRY")

    if je:
        pdf.kv_row("Entry ID:", je.get("entry_id", "—"), bold_value=True)
        pdf.kv_row("Entry Date:", str(je.get("entry_date", "—")))
        pdf.kv_row("Period:", je.get("accounting_period", "—"))
        pdf.kv_row("Reference:", je.get("reference", "—"))
        pdf.kv_row("Status:", je.get("status", "—"))
        pdf.kv_row("Total Debits:", _fmt_money(je.get("total_debits", 0)), bold_value=True)
        pdf.kv_row("Total Credits:", _fmt_money(je.get("total_credits", 0)), bold_value=True)
        bal = je.get("balanced", False)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(45, 5, "Balanced:")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*(GREEN if bal else RED))
        pdf.cell(0, 5, "YES" if bal else "NO — UNBALANCED", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

        # Lines table
        col_w2 = [8, 18, 60, 25, 25, 25, 19]
        hdrs2 = ["Seq", "Account", "Name", "Fund", "Debit", "Credit", "Approved By"]
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(*NAVY)
        pdf.set_text_color(*WHITE)
        for w, h in zip(col_w2, hdrs2):
            pdf.cell(w, 6, h, fill=True)
        pdf.ln(6)
        pdf.set_text_color(0, 0, 0)

        for i, line in enumerate(je.get("lines", [])):
            fill = i % 2 == 0
            pdf.set_fill_color(*LIGHT)
            pdf.set_font("Helvetica", "", 7)
            debit = _fmt_money(line.get("debit", 0)) if float(line.get("debit", 0)) else ""
            credit = _fmt_money(line.get("credit", 0)) if float(line.get("credit", 0)) else ""
            vals2 = [
                str(line.get("sequence", i + 1)),
                str(line.get("account_number", ""))[:8],
                str(line.get("account_name", ""))[:35],
                str(line.get("fund_name", ""))[:16],
                debit, credit,
                str(line.get("approved_by") or "")[:12],
            ]
            for w, v in zip(col_w2, vals2):
                pdf.cell(w, 5, v, fill=fill)
            pdf.ln(5)
    pdf.ln(3)

    # ── Page 4: Audit Log ────────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("PROCESSING AUDIT LOG")

    pdf.set_font("Helvetica", "", 7)
    for entry in audit_log:
        ts = entry.get("ts", "")[:19].replace("T", " ")
        status = entry.get("status", "")
        detail = entry.get("detail", "")
        pdf.set_text_color(*SLATE)
        pdf.cell(38, 5, ts)
        pdf.set_fill_color(*NAVY)
        pdf.set_text_color(*WHITE)
        pdf.set_font("Helvetica", "B", 6)
        sw = pdf.get_string_width(status) + 4
        pdf.cell(sw, 5, status, fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(5, 5, "")
        pdf.cell(0, 5, detail[:80], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path
