---
skill_name: pdf_extraction
archetype: worker
description: Extract structured invoice or payment data from a PDF file. Handles multi-page invoices, scanned images (via OCR), and common church vendor invoice layouts. Returns a validated InvoiceDocument JSON object.
inputs:
  - pdf_path
  - document_type
expected_output: InvoiceDocument with vendor_name, vendor_address, invoice_number, invoice_date, due_date, currency, subtotal, tax_amount, total_amount, payment_terms, memo, line_items[], warnings[], requires_manual_review.
allowed_tools:
  - pdf_read_tool
  - ocr_tool
  - document_schema_validator
---

# pdf_extraction

## Workflow Steps

1. Call pdf_read_tool with pdf_path. If scanned image, call ocr_tool.
2. Identify document_type from header. Flag mismatches as warnings.
3. Extract header fields: vendor name/address, invoice number, dates, PO, currency, payment terms.
4. Extract line item table. For service-style invoices, treat each paragraph as a single line item.
5. Extract subtotal, taxes, total, discounts.
6. Extract memo / remittance notes (often contains fund designations).
7. Apply document_schema_validator. Set missing required fields to null and add warnings; never fabricate.
8. If more than 3 required fields are null, set requires_manual_review=true with a reason string.
