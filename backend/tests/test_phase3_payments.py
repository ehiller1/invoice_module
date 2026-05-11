"""Phase 3.7 payment-initiation tests covering FR-08."""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from backend.models.schemas import JEStatus
from backend.tests.factories import JournalEntryFactory, VendorFactory


# ---- helpers ----

def _make_je(amount="100.00", entry_id="JE-TEST-001"):
    """Create a test JournalEntry.

    DEPRECATED: Use JournalEntryFactory.build() instead.
    Kept for backward compatibility.
    """
    return JournalEntryFactory.build(
        entry_id=entry_id,
        church_id="testch",
        debit_amount=amount,
        status=JEStatus.APPROVED,
        reference="INV-001",
        vendor_name="Acme Vendor",
        description="Test JE",
    )


@pytest.fixture
def tmp_payment_data(tmp_path, monkeypatch):
    """Redirect payment data dir into a tmp dir."""
    new_root = tmp_path / "data"
    new_root.mkdir()
    # Patch vendor_store
    from backend.tools import vendor_store
    monkeypatch.setattr(vendor_store, "DATA_ROOT", new_root)
    # Patch main module's payment dir helpers if present
    yield new_root


# ===== Vendor store =====

def test_vendor_store_round_trip(tmp_payment_data):
    from backend.models.schemas import PaymentMethod
    from backend.tools import vendor_store

    v = VendorFactory.build(
        vendor_id="V001",
        church_id="testch",
        name="Acme Vendor",
        ach_routing="123456789",
        ach_account_last4="1234",
    )
    saved = vendor_store.upsert_vendor("testch", v)
    assert saved.vendor_id == "V001"
    found = vendor_store.find_vendor_by_name("testch", "Acme Vendor")
    assert found is not None
    assert found.preferred_method == PaymentMethod.ACH
    # fuzzy lookup
    found2 = vendor_store.find_vendor_by_name("testch", "acme vendor inc")
    assert found2 is not None and found2.vendor_id == "V001"


# ===== Recommender =====

def test_recommend_payment_method_uses_vendor_preference():
    from backend.models.schemas import PaymentMethod
    from backend.tools.payment_recommender import recommend_payment_method

    je = _make_je()
    v = VendorFactory.build(vendor_id="V1", church_id="testch", name="Acme")
    rec = recommend_payment_method(je, v)
    assert rec["recommended"] == "ACH"
    assert "Acme" in rec["rationale"]


def test_recommend_payment_method_defaults_to_check_when_no_vendor():
    from backend.tools.payment_recommender import recommend_payment_method

    je = _make_je()
    rec = recommend_payment_method(je, None)
    assert rec["recommended"] == "CHECK"


# ===== NACHA =====

def test_nacha_file_format_correct_length():
    from backend.models.schemas import (
        PaymentInstruction, PaymentMethod, PaymentStatus, ACHRecord,
    )
    from backend.tools.nacha_generator import generate_nacha_file

    inst = PaymentInstruction(
        payment_id="PMT-1",
        church_id="testch",
        method=PaymentMethod.ACH,
        amount=Decimal("250.00"),
        status=PaymentStatus.APPROVED,
        ach_record=ACHRecord(
            routing_number="123456789",
            account_number_last4="1234",
            amount=Decimal("250.00"),
            payment_date=date(2026, 5, 6),
        ),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    content = generate_nacha_file([inst])
    lines = content.split("\n")
    # Each line must be exactly 94 chars
    for ln in lines:
        assert len(ln) == 94, f"line wrong length {len(ln)}: {ln!r}"
    # Should have header(1), batch-header(5), entry(6), batch-control(8), file-control(9)
    assert lines[0].startswith("1")
    assert lines[1].startswith("5")
    assert lines[2].startswith("6")
    assert lines[-2].startswith("8")
    assert lines[-1].startswith("9")


# ===== Check PDF =====

def test_check_pdf_generation_succeeds(tmp_path):
    from backend.models.schemas import (
        PaymentInstruction, PaymentMethod, PaymentStatus, CheckRecord,
    )
    from backend.tools.check_generator import generate_check_pdf

    inst = PaymentInstruction(
        payment_id="PMT-CK-1",
        church_id="testch",
        je_id="JE-001",
        method=PaymentMethod.CHECK,
        amount=Decimal("125.50"),
        status=PaymentStatus.APPROVED,
        check_record=CheckRecord(
            payee="Office Depot",
            amount=Decimal("125.50"),
            address="123 Main St",
            memo="Office supplies",
            check_date=date(2026, 5, 6),
        ),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    out = tmp_path / "check.pdf"
    result = generate_check_pdf(inst, str(out))
    assert Path(result).exists()
    assert Path(result).stat().st_size > 100


# ===== Endpoint tests (TestClient) =====

@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """TestClient wired against a tmp data dir for payments + JEs."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod
    from backend.tools import vendor_store

    new_data = tmp_path / "data"
    new_data.mkdir()
    monkeypatch.setattr(main_mod, "JE_DATA_DIR", new_data)
    # also patch the payment data dir
    monkeypatch.setattr(main_mod, "PAYMENT_DATA_DIR", new_data, raising=False)
    monkeypatch.setattr(vendor_store, "DATA_ROOT", new_data)

    return TestClient(main_mod.app)


def test_create_payment_for_je_uses_check_when_no_vendor(api_client, tmp_path, monkeypatch):
    from backend import main as main_mod

    je = _make_je(amount="200.00", entry_id="JE-EP-001")
    # persist as manual JE
    main_mod._persist_je("testch", je.model_dump())

    r = api_client.post(
        f"/api/jes/{je.entry_id}/payment",
        json={"method": "CHECK", "vendor_name": "Unknown Vendor"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "CHECK"
    assert body["amount"] == 200 or body["amount"] == "200.00" or float(body["amount"]) == 200.0
    assert body["check_record"]["payee"] == "Unknown Vendor"
    assert "recommendation" in body


def test_payment_endpoint_returns_recommendation(api_client, monkeypatch):
    from backend import main as main_mod
    from backend.tools import vendor_store
    from backend.models.schemas import Vendor, PaymentMethod

    v = Vendor(
        vendor_id="V99", church_id="testch", name="Preferred Vendor",
        payment_methods=[PaymentMethod.ACH, PaymentMethod.CHECK],
        preferred_method=PaymentMethod.ACH,
        ach_routing="987654321",
        ach_account_last4="9999",
    )
    vendor_store.upsert_vendor("testch", v)

    je = _make_je(amount="500.00", entry_id="JE-EP-002")
    main_mod._persist_je("testch", je.model_dump())

    r = api_client.post(
        f"/api/jes/{je.entry_id}/payment",
        json={"method": "ACH", "vendor_name": "Preferred Vendor"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "ACH"
    assert body["recommendation"]["recommended"] == "ACH"
    assert body["ach_record"] is not None


def test_approve_payment_transitions_to_approved(api_client):
    from backend import main as main_mod

    je = _make_je(amount="75.00", entry_id="JE-EP-003")
    main_mod._persist_je("testch", je.model_dump())

    r = api_client.post(
        f"/api/jes/{je.entry_id}/payment",
        json={"method": "CHECK", "vendor_name": "Some Vendor"},
    )
    assert r.status_code == 200
    pid = r.json()["payment_id"]

    r2 = api_client.post(
        f"/api/payments/{pid}/approve",
        json={"approver_email": "treasurer@church.org"},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "APPROVED"
    assert body["approved_by"] == "treasurer@church.org"
