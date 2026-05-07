"""Generate a simplified NACHA-format ACH file from PaymentInstructions.

NACHA file format requires every line to be exactly 94 characters wide; banks
will reject the file otherwise. This module writes the minimum five record
types required for an originator file:

    1 - File Header
    5 - Batch Header
    6 - Entry Detail (one per ACH payment)
    8 - Batch Control
    9 - File Control
"""
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import List

from backend.models.schemas import PaymentInstruction


LINE_WIDTH = 94


def _pad(line: str) -> str:
    """Truncate or right-pad a record to exactly 94 characters."""
    if len(line) > LINE_WIDTH:
        return line[:LINE_WIDTH]
    return line.ljust(LINE_WIDTH)


def generate_nacha_file(
    instructions: List[PaymentInstruction],
    originating_dfi: str = "12345678",
    company_name: str = "EIME CHURCH",
    company_id: str = "1234567890",
) -> str:
    """Generate a simplified NACHA file. Returns the file content as a string.

    Each line is guaranteed to be exactly 94 characters long.
    """
    today = date.today()
    odfi = (originating_dfi or "")[:10]
    odfi8 = odfi[:8].ljust(8, "0") if len(odfi) >= 8 else odfi.ljust(8, "0")

    # File Header (Record Type 1) -- 94 chars
    file_header = (
        "1"                                              # Record Type
        "01"                                             # Priority Code
        f" {odfi[:9]:<9}"                                # Immediate Destination (10)
        f"{odfi[:10]:<10}"                               # Immediate Origin (10)
        f"{today.strftime('%y%m%d')}"                    # File Creation Date (6)
        f"{datetime.now().strftime('%H%M')}"             # File Creation Time (4)
        "A"                                              # File ID Modifier (1)
        "094"                                            # Record Size (3)
        "10"                                             # Blocking Factor (2)
        "1"                                              # Format Code (1)
        f"{company_name[:23]:<23}"                       # Immediate Destination Name
        f"{'EIME CHURCH PMT':<23}"                       # Immediate Origin Name
        "        "                                       # Reference Code (8)
    )

    # Batch Header (Record Type 5)
    batch_header = (
        "5"                                              # Record Type
        "200"                                            # Service Class (mixed)
        f"{company_name[:16]:<16}"                       # Company Name
        f"{'':<20}"                                      # Discretionary Data
        f"{company_id[:10]:<10}"                         # Company ID
        "PPD"                                            # Standard Entry Class
        f"{'CHURCH PAY':<10}"                            # Company Entry Description
        f"{today.strftime('%y%m%d')}"                    # Descriptive Date
        f"{today.strftime('%y%m%d')}"                    # Effective Entry Date
        "   "                                            # Settlement Date / blank
        "1"                                              # Originator Status Code
        f"{odfi8}"                                       # Originating DFI ID
        "0000001"                                        # Batch Number
    )

    # Entry Detail records (Record Type 6)
    entries: List[str] = []
    total_amount = Decimal("0")
    entry_hash = 0
    for i, inst in enumerate(instructions):
        if not inst.ach_record:
            continue
        amount_cents = int((inst.amount * 100).to_integral_value())
        total_amount += inst.amount
        routing = (inst.ach_record.routing_number or "")[:9].rjust(9, "0")
        try:
            entry_hash += int(routing[:8])
        except ValueError:
            pass
        # ACS uses last4 only in our model; pad to 17 chars.
        acct_field = (inst.ach_record.account_number_last4 or "")[:17]
        vendor_label = ""
        if inst.cc_memo and inst.cc_memo.vendor_name:
            vendor_label = inst.cc_memo.vendor_name
        elif inst.check_record and inst.check_record.payee:
            vendor_label = inst.check_record.payee
        entry = (
            "6"                                          # Record Type
            "22"                                         # Transaction Code (checking credit)
            f"{routing}"                                 # Receiving DFI Routing (9)
            f"{acct_field:<17}"                          # DFI Account Number (17)
            f"{amount_cents:010d}"                       # Amount in cents (10)
            f"{inst.payment_id[:15]:<15}"                # Individual ID Number (15)
            f"{vendor_label[:22]:<22}"                   # Individual Name (22)
            "  "                                         # Discretionary Data (2)
            "0"                                          # Addenda Record Indicator (1)
            f"{odfi8}"                                   # Trace ODFI (8)
            f"{i+1:07d}"                                 # Trace Number Sequence (7)
        )
        entries.append(entry)

    # Batch Control (Record Type 8)
    total_cents = int((total_amount * 100).to_integral_value())
    entry_hash_str = f"{entry_hash % 10_000_000_000:010d}"
    batch_control = (
        "8"                                              # Record Type
        "200"                                            # Service Class
        f"{len(entries):06d}"                            # Entry/Addenda Count (6)
        f"{entry_hash_str}"                              # Entry Hash (10)
        f"{0:012d}"                                      # Total Debit Entry Dollar (12)
        f"{total_cents:012d}"                            # Total Credit Entry Dollar (12)
        f"{company_id[:10]:<10}"                         # Company ID
        f"{'':<19}"                                      # Message Authentication Code (19)
        f"{'':<6}"                                       # Reserved (6)
        f"{odfi8}"                                       # Originating DFI ID (8)
        "0000001"                                        # Batch Number (7)
    )

    # File Control (Record Type 9)
    total_records = 2 + len(entries) + 2  # header + batch_header + entries + batch_control + file_control
    # Records must be a multiple of 10 in NACHA, but we do a simplified count.
    file_control = (
        "9"                                              # Record Type
        "000001"                                         # Batch Count (6)
        f"{((total_records + 9) // 10):06d}"             # Block Count (6)
        f"{len(entries):08d}"                            # Entry/Addenda Count (8)
        f"{entry_hash_str}"                              # Entry Hash (10)
        f"{0:012d}"                                      # Total Debits (12)
        f"{total_cents:012d}"                            # Total Credits (12)
        f"{'':<39}"                                      # Reserved (39)
    )

    raw_lines = [file_header, batch_header] + entries + [batch_control, file_control]
    return "\n".join(_pad(ln) for ln in raw_lines)
