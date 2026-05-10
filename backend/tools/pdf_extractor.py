"""PDF extraction tool. Implements the pdf_read_tool/ocr_tool used by the pdf_extraction skill."""
from __future__ import annotations
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional
import re
import uuid

import pdfplumber
from pypdf import PdfReader

from ..models import DocumentType, InvoiceDocument, LineItem


CURRENCY_RE = re.compile(r"\$?\s*([\d,]+\.\d{2})")
DATE_RE = re.compile(r"\b(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})\b")
INV_RE = re.compile(r"(?:invoice|inv|bill)[\s#:no.]*([A-Z0-9\-]+)", re.IGNORECASE)
PO_RE = re.compile(r"(?:po|p\.o\.)[\s#:no.]*([A-Z0-9\-]+)", re.IGNORECASE)


def _to_decimal(s: str) -> Decimal:
    try:
        return Decimal(s.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def _parse_date(s: str) -> Optional[date]:
    m = DATE_RE.search(s)
    if not m:
        return None
    mo, d, y = m.groups()
    y_int = int(y)
    if y_int < 100:
        y_int += 2000
    try:
        return date(y_int, int(mo), int(d))
    except ValueError:
        return None


def extract_text(pdf_path: str) -> str:
    """Extract text from a PDF.

    Strategy (in order):
      1. pdfplumber  — best for native-text PDFs (tables, columns)
      2. pypdf       — fallback for simple text-layer PDFs
      3. pytesseract — OCR fallback for scanned/image-only PDFs
    """
    text_parts: List[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_parts.append(t)
    except Exception:
        pass
    text = "\n".join(text_parts).strip()
    if not text:
        try:
            reader = PdfReader(pdf_path)
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            text = ""

    # HTML fallback: file saved as .pdf but is actually HTML (e.g. browser-printed
    # invoices that were captured as raw HTML instead of rendered PDF).
    if not text.strip():
        try:
            raw = Path(pdf_path).read_bytes()
            if raw.lstrip()[:15].lower().startswith((b"<!doc", b"<html")):
                from html.parser import HTMLParser

                class _TextCollector(HTMLParser):
                    def __init__(self) -> None:
                        super().__init__()
                        self._parts: List[str] = []
                        self._skip = False

                    def handle_starttag(self, tag: str, attrs: Any) -> None:
                        if tag in ("script", "style"):
                            self._skip = True

                    def handle_endtag(self, tag: str) -> None:
                        if tag in ("script", "style"):
                            self._skip = False

                    def handle_data(self, data: str) -> None:
                        if not self._skip and data.strip():
                            self._parts.append(data.strip())

                    def get_text(self) -> str:
                        return "\n".join(self._parts)

                collector = _TextCollector()
                collector.feed(raw.decode("utf-8", errors="replace"))
                text = collector.get_text()
        except Exception:
            text = ""

    # OCR fallback: when all text extractors return nothing the PDF is likely a
    # scanned image.  Use pdfplumber's page renderer + pytesseract.
    if not text.strip():
        try:
            import pytesseract  # type: ignore

            ocr_parts: List[str] = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    # render at 200 dpi — good balance of speed vs accuracy
                    img = page.to_image(resolution=200).original
                    ocr_parts.append(pytesseract.image_to_string(img))
            text = "\n".join(ocr_parts).strip()
        except Exception:
            text = ""

    return text


def _extract_amounts_section(text: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {"subtotal": Decimal("0"), "tax_amount": Decimal("0"), "total_amount": Decimal("0")}
    for line in text.splitlines():
        low = line.lower()
        m = CURRENCY_RE.search(line)
        if not m:
            continue
        amt = _to_decimal(m.group(1))
        if "subtotal" in low and out["subtotal"] == 0:
            out["subtotal"] = amt
        elif ("tax" in low or "vat" in low) and out["tax_amount"] == 0:
            out["tax_amount"] = amt
        elif ("total due" in low or "amount due" in low or "grand total" in low or low.strip().startswith("total")) and out["total_amount"] == 0:
            out["total_amount"] = amt
    if out["total_amount"] == 0 and out["subtotal"] > 0:
        out["total_amount"] = out["subtotal"] + out["tax_amount"]
    return out


def _extract_line_items(text: str, fallback_total: Decimal) -> List[LineItem]:
    """Heuristic line item extraction. Looks for $X.XX patterns with descriptions."""
    items: List[LineItem] = []
    lines = [ln.rstrip() for ln in text.splitlines()]
    skip_keywords = ("subtotal", "tax", "total", "balance", "amount due", "thank you",
                     "invoice", "date", "vendor", "bill to", "ship to", "po ", "terms",
                     "payment", "due", "remit", "address", "phone", "email", "page")
    for ln in lines:
        low = ln.lower()
        if any(k in low for k in skip_keywords):
            continue
        m = CURRENCY_RE.search(ln)
        if not m:
            continue
        amt = _to_decimal(m.group(1))
        if amt <= 0:
            continue
        desc = CURRENCY_RE.sub("", ln).strip(" -|\t")
        desc = re.sub(r"\s{2,}", " ", desc)
        if len(desc) < 3:
            continue
        items.append(LineItem(
            line_id=f"L{len(items)+1:03d}",
            description=desc[:200],
            quantity=Decimal("1"),
            unit_price=amt,
            amount=amt,
        ))
    if not items and fallback_total > 0:
        # Service-style: treat the whole document as one line
        first_paragraph = next((ln for ln in lines if len(ln.strip()) > 10), "Unspecified service")
        items.append(LineItem(
            line_id="L001",
            description=first_paragraph.strip()[:200],
            quantity=Decimal("1"),
            unit_price=fallback_total,
            amount=fallback_total,
        ))
    return items


def _extract_vendor(text: str) -> str:
    """First non-empty line is usually the vendor."""
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        # Skip lines that look like 'Invoice' headers
        if re.match(r"^(invoice|bill|statement|receipt)\b", s, re.IGNORECASE):
            continue
        return s[:120]
    return "Unknown Vendor"


def _extract_vendor_address(text: str) -> Optional[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return None
    # Take 1-3 lines after the vendor name as a tentative address
    address_chunks: List[str] = []
    for ln in lines[1:5]:
        if re.match(r"^(invoice|bill|date|amount|po|terms)", ln, re.IGNORECASE):
            break
        address_chunks.append(ln)
    return "\n".join(address_chunks) if address_chunks else None


def _extract_invoice_number(text: str) -> str:
    m = INV_RE.search(text)
    return m.group(1) if m else f"AUTO-{uuid.uuid4().hex[:8].upper()}"


def _extract_dates(text: str) -> tuple[Optional[date], Optional[date]]:
    invoice_date = None
    due_date = None
    for ln in text.splitlines():
        low = ln.lower()
        d = _parse_date(ln)
        if not d:
            continue
        if invoice_date is None and ("date" in low and "due" not in low):
            invoice_date = d
        elif due_date is None and "due" in low:
            due_date = d
    if invoice_date is None:
        invoice_date = _parse_date(text) or date.today()
    return invoice_date, due_date


def _extract_memo(text: str) -> Optional[str]:
    """Look for memo / remittance / fund designation language."""
    memo_lines: List[str] = []
    for ln in text.splitlines():
        low = ln.lower()
        if any(k in low for k in ("memo:", "note:", "for:", "designation:", "fund:", "purpose:")):
            memo_lines.append(ln.strip())
    return " | ".join(memo_lines)[:500] if memo_lines else None


def extract_invoice(pdf_path: str, document_type: DocumentType) -> InvoiceDocument:
    """End-to-end extraction implementing the pdf_extraction skill workflow."""
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(pdf_path)
    text = extract_text(pdf_path)
    warnings: List[str] = []
    if not text.strip():
        warnings.append("PDF text could not be extracted (scanned image PDF with no OCR output).")
        text = "Unknown vendor\nInvoice 0\nTotal $0.00"

    vendor = _extract_vendor(text)
    address = _extract_vendor_address(text)
    invoice_number = _extract_invoice_number(text)
    invoice_date, due_date = _extract_dates(text)
    amounts = _extract_amounts_section(text)
    line_items = _extract_line_items(text, amounts["total_amount"])
    memo = _extract_memo(text)

    if amounts["total_amount"] == 0 and line_items:
        total_li: Decimal = Decimal("0")
        for li in line_items:
            total_li += li.amount
        amounts["total_amount"] = total_li
    if amounts["subtotal"] == 0:
        amounts["subtotal"] = amounts["total_amount"] - amounts["tax_amount"]

    required_missing = 0
    if vendor == "Unknown Vendor":
        warnings.append("Vendor name could not be determined.")
        required_missing += 1
    if invoice_number.startswith("AUTO-"):
        warnings.append("Invoice number not found; auto-assigned reference used.")
        required_missing += 1
    if amounts["total_amount"] == 0:
        warnings.append("Total amount could not be parsed.")
        required_missing += 1

    return InvoiceDocument(
        vendor_name=vendor,
        vendor_address=address,
        invoice_number=invoice_number,
        invoice_date=invoice_date or date.today(),
        due_date=due_date,
        document_type=document_type,
        currency="USD",
        subtotal=amounts["subtotal"],
        tax_amount=amounts["tax_amount"],
        total_amount=amounts["total_amount"],
        memo=memo,
        line_items=line_items,
        warnings=warnings,
        requires_manual_review=required_missing >= 3,
        raw_text=text,
    )
