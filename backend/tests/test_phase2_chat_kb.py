"""Phase 2.8 + 2.9 — Manual JE via chat (FR-06.2) and Knowledge Base (FR-09)."""
from __future__ import annotations

import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.models.schemas import (
    Account, AccountingContext, DenominationType, Fund, FundCategory,
    JEStatus, JournalEntry, JournalEntryLine, RestrictionClass,
)


# ---------------------------------------------------------------------------
# Fixtures: redirect ChromaDB + data dirs to tmp so tests are hermetic
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """Re-point coa_store.DATA_ROOT, knowledge_base data dirs, and main JE
    storage to a temp directory."""
    from backend.tools import coa_store, knowledge_base
    from backend import main as main_mod

    new_data = tmp_path / "data"
    new_data.mkdir()
    new_chroma = new_data / "chroma"
    new_chroma.mkdir()
    new_kb_root = new_data / "kb"
    new_kb_root.mkdir()

    # coa_store
    monkeypatch.setattr(coa_store, "DATA_ROOT", new_data)
    monkeypatch.setattr(coa_store, "CHROMA_DIR", new_chroma)
    monkeypatch.setattr(coa_store, "_chroma_client", None)

    # knowledge_base — fresh chroma client + KB file root
    monkeypatch.setattr(knowledge_base, "_DATA_ROOT", new_data)
    monkeypatch.setattr(knowledge_base, "_CHROMA_DIR", new_chroma)
    monkeypatch.setattr(knowledge_base, "_KB_FILES_ROOT", new_kb_root)
    monkeypatch.setattr(knowledge_base, "_chroma_client", None)

    # main.py JE store + KB upload root
    monkeypatch.setattr(main_mod, "JE_DATA_DIR", new_data)
    monkeypatch.setattr(main_mod, "KB_FILES_ROOT", new_kb_root)

    yield {
        "data": new_data,
        "chroma": new_chroma,
        "kb_root": new_kb_root,
    }


@pytest.fixture
def seeded_church(isolated_data):
    """Persist a small church with two cash + two expense accounts."""
    from backend.tools import coa_store
    ctx = AccountingContext(
        church_id="hc",
        church_name="Holy Comforter",
        denomination_type=DenominationType.EPISCOPAL,
        fiscal_year=2026,
        fiscal_year_start=date(2026, 1, 1),
        accounts=[
            Account(account_number="1010",
                    account_name="Holy Comforter Operating Cash",
                    account_type="Asset", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
            Account(account_number="1020",
                    account_name="Friendship Center Cash",
                    account_type="Asset", fund_id="OUTREACH",
                    restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE),
            Account(account_number="6500",
                    account_name="Maintenance",
                    account_type="Expense", fund_id="GEN",
                    restriction_class=RestrictionClass.WITHOUT_RESTRICTION),
        ],
        funds=[
            Fund(fund_id="GEN", fund_name="General",
                 restriction_class=RestrictionClass.WITHOUT_RESTRICTION,
                 fund_category=FundCategory.GENERAL_OPERATING),
            Fund(fund_id="OUTREACH", fund_name="Outreach",
                 restriction_class=RestrictionClass.WITH_RESTRICTION_PURPOSE,
                 fund_category=FundCategory.TEMP_RESTRICTED_PURPOSE),
        ],
    )
    coa_store.save_accounting_context(ctx)
    return ctx


@pytest.fixture
def client(isolated_data):
    from backend.main import app
    return TestClient(app)


# ===========================================================================
# 2.8 — Chat intent classification & manual JE drafting
# ===========================================================================

def test_chat_intent_create_manual_je_classifies_correctly():
    """Heuristic classifier should detect 'create JE' intent regardless of
    whether the Anthropic API is available — Claude is mocked."""
    from backend.tools.chat_router import classify_intent, INTENT_CREATE_MANUAL_JE

    yes = [
        "Create a journal entry to transfer $1000 from operating cash to outreach",
        "Please record a journal entry for the gas bill",
        "Make a JE to move $250 to maintenance",
        "transfer $500 from operating cash to outreach fund",
    ]
    for q in yes:
        assert classify_intent(q) == INTENT_CREATE_MANUAL_JE, q

    no = [
        "What is the status of invoice INV-123?",
        "Why was this allocation flagged?",
        "Show me the budget",
    ]
    for q in no:
        assert classify_intent(q) != INTENT_CREATE_MANUAL_JE, q


def test_build_manual_je_draft_balanced(seeded_church):
    """Given hints + ctx, build_manual_je_draft returns a balanced draft."""
    from backend.tools.chat_router import build_manual_je_draft

    # Stub the Claude extractor so the test does not call the network.
    fake_slots = {
        "from_account_hint": "operating cash",
        "to_account_hint": "Friendship Center",
        "amount": 1000.0,
        "fund_hint": None,
        "memo": "Q4 outreach transfer",
    }
    with patch("backend.tools.chat_router._extract_je_slots_with_claude",
               return_value=fake_slots):
        draft = build_manual_je_draft(
            church_id=seeded_church.church_id,
            question="Create a journal entry to transfer $1000",
            ctx=seeded_church,
        )

    assert draft["type"] == "manual_je_draft"
    assert draft["confirmation_required"] is True
    assert draft["errors"] == []
    je = draft["je_draft"]
    assert je is not None
    assert je["balanced"] is True
    assert Decimal(str(je["total_debits"])) == Decimal("1000")
    assert Decimal(str(je["total_credits"])) == Decimal("1000")
    assert len(je["lines"]) == 2
    debit_line = next(ln for ln in je["lines"]
                      if Decimal(str(ln["debit"])) > 0)
    credit_line = next(ln for ln in je["lines"]
                       if Decimal(str(ln["credit"])) > 0)
    assert "Friendship" in debit_line["account_name"]
    assert "Operating" in credit_line["account_name"]


def test_manual_je_create_endpoint_balanced_je_succeeds(client, seeded_church):
    """POST a balanced JE — endpoint persists it and returns DRAFT status."""
    je = JournalEntry(
        entry_id="JE-MANUAL-TEST1",
        church_id=seeded_church.church_id,
        fiscal_year=2026,
        accounting_period="2026-05",
        entry_date=date(2026, 5, 6),
        reference="MANUAL-TEST1",
        vendor_name="Manual Entry",
        description="Test transfer",
        status=JEStatus.DRAFT,
        lines=[
            JournalEntryLine(
                sequence=1, account_number="1020",
                account_name="Friendship Center Cash",
                fund_id="OUTREACH", fund_name="Outreach",
                debit=Decimal("1000"), credit=Decimal("0"), memo="Test",
            ),
            JournalEntryLine(
                sequence=2, account_number="1010",
                account_name="Holy Comforter Operating Cash",
                fund_id="GEN", fund_name="General",
                debit=Decimal("0"), credit=Decimal("1000"), memo="Test",
            ),
        ],
        total_debits=Decimal("1000"),
        total_credits=Decimal("1000"),
        balanced=True,
        audit_trail_url="",
    )
    payload = json.loads(je.model_dump_json())

    r = client.post("/api/jes/manual-create", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["status"] == "DRAFT"
    assert data["entry_id"] == "JE-MANUAL-TEST1"

    # Verify it was persisted
    r2 = client.get(f"/api/churches/{seeded_church.church_id}/jes/manual")
    assert r2.status_code == 200
    rows = r2.json()
    assert any(row["entry_id"] == "JE-MANUAL-TEST1" for row in rows)


def test_manual_je_create_endpoint_unbalanced_je_returns_422(client, seeded_church):
    """An unbalanced JE must be rejected with HTTP 422."""
    je = JournalEntry(
        entry_id="JE-UNBAL-1",
        church_id=seeded_church.church_id,
        fiscal_year=2026,
        accounting_period="2026-05",
        entry_date=date(2026, 5, 6),
        reference="UNBAL-1",
        vendor_name="Manual Entry",
        description="Bad transfer",
        status=JEStatus.DRAFT,
        lines=[
            JournalEntryLine(
                sequence=1, account_number="1020",
                account_name="Friendship Center Cash",
                fund_id="OUTREACH", fund_name="Outreach",
                debit=Decimal("1000"), credit=Decimal("0"),
            ),
            JournalEntryLine(
                sequence=2, account_number="1010",
                account_name="Holy Comforter Operating Cash",
                fund_id="GEN", fund_name="General",
                debit=Decimal("0"), credit=Decimal("750"),
            ),
        ],
        total_debits=Decimal("1000"),
        total_credits=Decimal("750"),
        balanced=False,
        audit_trail_url="",
    )
    r = client.post("/api/jes/manual-create",
                    json=json.loads(je.model_dump_json()))
    assert r.status_code == 422, r.text


# ===========================================================================
# 2.9 — Knowledge Base
# ===========================================================================

def test_kb_upload_md_file_creates_chunks(client, seeded_church, tmp_path):
    """Uploading a Markdown file ingests it into ChromaDB and reports chunk count."""
    md = (
        "# Holy Comforter Discretionary Fund Policy\n\n"
        "## Section 1 — Authority\n\n"
        "The Rector may disburse from the Discretionary Fund for charitable "
        "purposes consistent with TEC Title I, Canon 7.\n\n"
        "## Section 2 — Audit\n\n"
        "Disbursements are reviewed quarterly by the vestry treasurer.\n"
    )
    files = {"file": ("policy.md", md.encode("utf-8"), "text/markdown")}
    r = client.post(f"/api/churches/{seeded_church.church_id}/kb/upload",
                    files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["filename"] == "policy.md"
    assert data["chunk_count"] >= 1

    # listing should contain the file
    r2 = client.get(f"/api/churches/{seeded_church.church_id}/kb/list")
    assert r2.status_code == 200
    files_list = r2.json()
    assert any(f["filename"] == "policy.md" and f["chunk_count"] >= 1
               for f in files_list)


def test_kb_upload_idempotent(client, seeded_church):
    """Re-uploading the same filename must replace, not duplicate, chunks."""
    md = "## Policy A\n\nFirst version of the policy.\n"
    files = {"file": ("policy.md", md.encode("utf-8"), "text/markdown")}
    r1 = client.post(f"/api/churches/{seeded_church.church_id}/kb/upload",
                     files=files)
    assert r1.status_code == 200
    first_count = r1.json()["chunk_count"]

    # Re-upload (different content, same filename)
    md2 = "## Policy A\n\nSecond version replaces the first.\n"
    files2 = {"file": ("policy.md", md2.encode("utf-8"), "text/markdown")}
    r2 = client.post(f"/api/churches/{seeded_church.church_id}/kb/upload",
                     files=files2)
    assert r2.status_code == 200

    # listing should still show 1 file with the *new* chunk count, not double
    r3 = client.get(f"/api/churches/{seeded_church.church_id}/kb/list")
    files_list = r3.json()
    targets = [f for f in files_list if f["filename"] == "policy.md"]
    assert len(targets) == 1
    # Chunk count should equal what r2 produced (not first_count + r2_count).
    assert targets[0]["chunk_count"] == r2.json()["chunk_count"]


def test_kb_search_returns_relevant_hits_with_citations(client, seeded_church):
    """Search returns hits with non-empty citation strings."""
    md = (
        "## Discretionary Fund Procedure\n\n"
        "All disbursements from the rector's discretionary fund must have a "
        "memo attached describing the charitable purpose.\n"
    )
    files = {"file": ("discretionary.md", md.encode("utf-8"), "text/markdown")}
    client.post(f"/api/churches/{seeded_church.church_id}/kb/upload",
                files=files)

    r = client.get(
        f"/api/churches/{seeded_church.church_id}/kb/search",
        params={"q": "discretionary fund disbursements", "k": 3},
    )
    assert r.status_code == 200, r.text
    hits = r.json()
    assert isinstance(hits, list)
    assert len(hits) >= 1
    # Every hit must have a non-empty citation field.
    for h in hits:
        assert "citation" in h
        assert h["citation"], f"Empty citation in hit: {h}"


def test_kb_delete_removes_chunks_from_collection(client, seeded_church):
    """Deleting a doc removes both the file and its ChromaDB chunks."""
    md = "## Section A\n\nSome content for deletion test.\n"
    files = {"file": ("to_delete.md", md.encode("utf-8"), "text/markdown")}
    client.post(f"/api/churches/{seeded_church.church_id}/kb/upload",
                files=files)

    r = client.delete(
        f"/api/churches/{seeded_church.church_id}/kb/to_delete.md"
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # listing should no longer show the file
    r2 = client.get(f"/api/churches/{seeded_church.church_id}/kb/list")
    files_list = r2.json()
    assert all(f["filename"] != "to_delete.md" for f in files_list)

    # And searching that content should not return it
    from backend.tools import knowledge_base
    hits = knowledge_base.kb_search_church(
        "deletion test", church_id=seeded_church.church_id, k=5,
    )
    assert all("to_delete.md" not in (h.source_filename or "") for h in hits)


def test_chat_router_includes_kb_hits_in_context(seeded_church):
    """End-to-end: chat router must inject KB citations into the system prompt
    that goes to Claude. Claude itself is mocked."""
    import asyncio
    from backend.tools import chat_router, knowledge_base

    # Seed per-church KB with one doc.
    md = (
        "## Holy Comforter Memo Requirements\n\n"
        "Every journal entry posted at Holy Comforter must include a memo "
        "describing the business purpose.\n"
    )
    # Write to disk + ingest (mimics the upload endpoint).
    kb_dir = knowledge_base._church_kb_dir(seeded_church.church_id)
    fp = kb_dir / "memo_requirements.md"
    fp.write_text(md, encoding="utf-8")
    knowledge_base.ingest_church_kb(seeded_church.church_id, fp)

    # Simulate ANTHROPIC_API_KEY being set so the QA branch fires.
    captured: Dict[str, Any] = {}

    class _FakeMsg:
        usage = MagicMock(input_tokens=1, output_tokens=1)
        content = [MagicMock(text="Per the memo requirements policy, every JE needs a memo.")]

    class _FakeClient:
        def __init__(self, *a, **kw):
            self.messages = self
        def create(self, *, model, max_tokens, system, messages):
            captured["system"] = system
            captured["messages"] = messages
            captured["model"] = model
            return _FakeMsg()

    fake_anth = MagicMock()
    fake_anth.Anthropic = _FakeClient

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=False), \
         patch.dict("sys.modules", {"anthropic": fake_anth}):
        result = asyncio.run(chat_router.route_question(
            question="What are Holy Comforter's memo requirements?",
            job=None,
            church_id=seeded_church.church_id,
        ))

    # The system prompt must reference the KB hits header + citation.
    assert "Relevant church accounting reference" in captured["system"]
    assert "Memo Requirements" in captured["system"] \
        or "memo_requirements" in captured["system"].lower() \
        or "Memo" in captured["system"]
    # The router should have surfaced kb_citations on the response.
    assert isinstance(result.get("kb_citations"), list)
    assert any(c for c in result["kb_citations"])
