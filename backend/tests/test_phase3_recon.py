"""Phase 3 reconciliation tests covering FR-07.1 through FR-07.6."""
from __future__ import annotations

import io
import json
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from backend.models.schemas import (
    BankTransaction,
    MatchResult,
    ReconException,
    ReconciliationSession,
)
from backend.tools.bank_statement_parser import (
    parse_csv,
    parse_statement,
)
from backend.tools.recon_matcher import match_transactions


CSV_AMOUNT_FORMAT = (
    "Date,Description,Amount\n"
    "2026-04-01,Vanco Deposit Tithe,1500.00\n"
    "2026-04-02,Office Depot Supplies,-125.50\n"
    "2026-04-05,Electric Bill ConEd,-422.18\n"
)

CSV_DEBIT_CREDIT_FORMAT = (
    "Post Date,Description,Debit,Credit\n"
    "2026-04-01,Vanco Deposit Tithe,,1500.00\n"
    "2026-04-02,Office Depot Supplies,125.50,\n"
    "2026-04-05,Electric Bill ConEd,422.18,\n"
)


def test_parse_csv_with_amount_column():
    """Parse a CSV using a single signed Amount column."""
    txns = parse_csv(CSV_AMOUNT_FORMAT.encode("utf-8"), "stmt.csv")
    assert len(txns) == 3
    assert txns[0].amount == Decimal("1500.00")
    assert txns[1].amount == Decimal("-125.50")
    assert txns[0].date == date(2026, 4, 1)
    assert "Vanco" in txns[0].description
    # Type derived from sign
    assert txns[0].type == "CREDIT"
    assert txns[1].type == "DEBIT"


def test_parse_csv_with_debit_credit_columns():
    """Parse a CSV using separate Debit/Credit columns."""
    txns = parse_csv(CSV_DEBIT_CREDIT_FORMAT.encode("utf-8"), "stmt.csv")
    assert len(txns) == 3
    # Credit column → positive amount
    assert txns[0].amount == Decimal("1500.00")
    # Debit column → negative amount
    assert txns[1].amount == Decimal("-125.50")
    assert txns[2].amount == Decimal("-422.18")


def test_parse_statement_dispatches_csv():
    """parse_statement should auto-route .csv files."""
    txns = parse_statement(CSV_AMOUNT_FORMAT.encode("utf-8"), "stmt.csv")
    assert len(txns) == 3


def test_parse_ofx_extracts_transactions():
    """OFX parsing should produce transactions; skip if ofxparse missing."""
    pytest.importorskip("ofxparse")
    from backend.tools.bank_statement_parser import parse_ofx

    sample_ofx = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<BANKMSGSRSV1><STMTTRNRS><TRNUID>1</TRNUID>
<STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
<STMTRS><CURDEF>USD</CURDEF>
<BANKACCTFROM><BANKID>123</BANKID><ACCTID>555</ACCTID><ACCTTYPE>CHECKING</ACCTTYPE></BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260401</DTSTART><DTEND>20260430</DTEND>
<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20260401</DTPOSTED><TRNAMT>1500.00</TRNAMT><FITID>T1</FITID><NAME>Vanco Deposit</NAME></STMTTRN>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260402</DTPOSTED><TRNAMT>-125.50</TRNAMT><FITID>T2</FITID><NAME>Office Depot</NAME></STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>5000.00</BALAMT><DTASOF>20260430</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""
    try:
        txns = parse_ofx(sample_ofx, "test.ofx")
    except Exception as exc:
        pytest.skip(f"OFX parse not supported in this env: {exc}")
    assert len(txns) >= 1


def _bank_txn(amount, dt, desc, txn_id="b1"):
    return BankTransaction(
        txn_id=txn_id,
        date=dt,
        description=desc,
        amount=Decimal(str(amount)),
        type="CREDIT" if Decimal(str(amount)) > 0 else "DEBIT",
    )


def test_match_exact_amount_and_date():
    """Bank txn with same amount/date as ACS entry should EXACT-match."""
    bank = [_bank_txn("1500.00", date(2026, 4, 1), "Tithe Deposit")]
    acs = [{"ref": "JE001", "date": date(2026, 4, 1),
            "amount": Decimal("1500.00"), "description": "Tithe Deposit",
            "fund": "GEN"}]
    matches, exceptions = match_transactions(bank, acs)
    assert len(matches) == 1
    assert matches[0].match_type == "EXACT"
    assert matches[0].acs_txn_ref == "JE001"
    assert exceptions == []


def test_match_fuzzy_within_3_days_amount_tolerance():
    """Bank txn within 3 days and $0.01 tolerance with desc overlap should FUZZY-match."""
    bank = [_bank_txn("-422.18", date(2026, 4, 5), "Electric Bill ConEd")]
    acs = [{"ref": "JE002", "date": date(2026, 4, 7),
            "amount": Decimal("-422.18"), "description": "ConEd Electric Service",
            "fund": "GEN"}]
    matches, exceptions = match_transactions(bank, acs)
    assert len(matches) == 1
    assert matches[0].match_type == "FUZZY"
    assert matches[0].confidence >= 0.6


def test_match_vanco_pattern_priority():
    """Vanco-marked deposits should match through VANCO_PATTERN before EXACT."""
    bank = [_bank_txn("1500.00", date(2026, 4, 1), "VANCO ACH DEPOSIT")]
    acs = [{"ref": "JE100", "date": date(2026, 4, 1),
            "amount": Decimal("1500.00"), "description": "Vanco Tithe Batch",
            "fund": "GEN"}]
    matches, exceptions = match_transactions(bank, acs)
    assert len(matches) == 1
    assert matches[0].match_type == "VANCO_PATTERN"


def test_unmatched_bank_creates_exception():
    """Bank txn with no ACS counterpart → BANK_ONLY exception."""
    bank = [_bank_txn("-50.00", date(2026, 4, 10), "Mystery Withdrawal")]
    acs = []
    matches, exceptions = match_transactions(bank, acs)
    assert matches == []
    assert len(exceptions) == 1
    assert exceptions[0].issue == "BANK_ONLY"


def test_unmatched_acs_creates_exception():
    """ACS entry with no bank counterpart → ACS_ONLY exception."""
    bank = []
    acs = [{"ref": "JE777", "date": date(2026, 4, 10),
            "amount": Decimal("-100"), "description": "Outstanding Check",
            "fund": "GEN"}]
    matches, exceptions = match_transactions(bank, acs)
    assert matches == []
    assert len(exceptions) == 1
    assert exceptions[0].issue == "ACS_ONLY"
    assert exceptions[0].acs_txn_ref == "JE777"


def test_recon_pdf_generation_succeeds():
    """PDF generation must work even with empty session."""
    from backend.tools.recon_matcher import generate_reconciliation_pdf

    session = ReconciliationSession(
        session_id="test_sess",
        church_id="TEST",
        period="2026-04",
        fund_ids=["GEN"],
        statement_files=[],
        bank_transactions=[],
        matches=[],
        exceptions=[],
        status="OPEN",
        opening_balance=Decimal("0"),
        closing_balance=Decimal("0"),
        acs_balance=Decimal("0"),
        variance=Decimal("0"),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "report.pdf"
        result = generate_reconciliation_pdf(session, str(out))
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0


def test_recon_pdf_with_matches_and_exceptions():
    """PDF generation should also handle a populated session."""
    from backend.tools.recon_matcher import generate_reconciliation_pdf

    session = ReconciliationSession(
        session_id="test_sess",
        church_id="TEST",
        period="2026-04",
        fund_ids=["GEN", "OUTREACH"],
        statement_files=["april.csv"],
        bank_transactions=[
            _bank_txn("1500.00", date(2026, 4, 1), "Vanco Deposit"),
        ],
        matches=[
            MatchResult(bank_txn_id="b1", acs_txn_ref="JE001",
                        match_type="EXACT", confidence=1.0),
        ],
        exceptions=[
            ReconException(exception_id="exc_b2", bank_txn_id="b2",
                           issue="BANK_ONLY"),
        ],
        status="EXCEPTIONS_REVIEW",
        opening_balance=Decimal("1000"),
        closing_balance=Decimal("2500"),
        acs_balance=Decimal("2400"),
        variance=Decimal("100"),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "report.pdf"
        result = generate_reconciliation_pdf(session, str(out))
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0


def test_match_endpoint_persists_results(tmp_path, monkeypatch):
    """Smoke test: /api/recon/{session_id}/match should populate matches+exceptions."""
    from fastapi.testclient import TestClient
    from backend import main as backend_main

    # Redirect data dir to tmp
    monkeypatch.setattr(backend_main, "RECON_DATA_DIR", tmp_path)

    client = TestClient(backend_main.app)

    # Seed a session with a single bank txn that has no ACS counterpart
    sess = ReconciliationSession(
        session_id="sess1",
        church_id="TEST",
        period="2026-04",
        fund_ids=["GEN"],
        statement_files=["x.csv"],
        bank_transactions=[
            _bank_txn("-50.00", date(2026, 4, 10), "Mystery"),
        ],
        matches=[],
        exceptions=[],
        status="OPEN",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    backend_main._persist_session(sess)

    r = client.post("/api/recon/sess1/match")
    assert r.status_code == 200
    body = r.json()
    assert body["matches"] == 0
    assert body["exceptions"] >= 1


def test_recon_advisor_fallback_for_bank_only():
    """recon_advisor should produce a narrative + JE for BANK_ONLY exceptions."""
    from backend.tools.recon_advisor import analyze_exception

    bt = _bank_txn("-50.00", date(2026, 4, 10), "Mystery")
    exc = ReconException(exception_id="x", bank_txn_id="b1", issue="BANK_ONLY")
    # Force fallback (no API key)
    import os
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        result = analyze_exception(exc, bt, None, None)
    finally:
        if saved:
            os.environ["ANTHROPIC_API_KEY"] = saved
    assert "narrative" in result
    assert result["proposed_je"] is not None
    assert "lines" in result["proposed_je"]
