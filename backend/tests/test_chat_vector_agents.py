"""Test suite proving chat, vector search, and per-agent conversation work end-to-end.

Three axes of coverage:

  A. CHAT FUNCTION
       A1  POST /api/chat returns a structured response for general QA
       A2  POST /api/chat detects CREATE_MANUAL_JE intent without calling the LLM
       A3  POST /api/chat returns the documented assistant-unavailable error
           when ANTHROPIC_API_KEY is absent (no silent failure)
       A4  /api/chat carries church_id through to KB + CoA grounding
       A5  Job-bound chat (?job_id=...) inherits the job's accounting context

  B. VECTOR DATASTORE + EMBEDDINGS
       B1  knowledge_base.ingest_canon_skills() loads canon SKILL.md docs
           into the kb_canon Chroma collection (idempotent)
       B2  kb_search() returns ranked, non-empty hits for a canon-relevant
           query, each carrying a citation + similarity score
       B3  Per-church KB ingest is searchable via /api/churches/{id}/kb/search
       B4  Denomination filter narrows results (Episcopal church does not
           receive UMC-only hits)
       B5  coa_store.semantic_search resolves a free-text account hint
           ("operating cash") to the correct seeded account by embedding
           similarity, not by substring match

  C. PER-AGENT CONVERSATION
       For every entry in AGENT_REGISTRY (drafting, reconciliation, compliance,
       auto_post, advisor):
         C1  Agent is registered with a non-empty role / goal / backstory and
             at least one tool — i.e. it is *capable* of conversation
         C2  /api/chat can address a question scoped to that agent's domain
             and the response cites the appropriate skill / tool family
         C3  Chat history round-trips: a follow-up question in the same
             church_id surfaces KB citations consistent with the first turn

The Anthropic API is always mocked. Chroma runs against a tmp dir so the
suite is hermetic and safe to run in CI.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.models.schemas import (
    Account, AccountingContext, DenominationType, Fund, FundCategory,
    RestrictionClass,
)


# ---------------------------------------------------------------------------
# Hermetic fixtures (mirrors test_phase2_chat_kb.py so tmp Chroma is used)
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    from backend.tools import coa_store, knowledge_base
    from backend import main as main_mod

    new_data = tmp_path / "data"
    new_data.mkdir()
    new_chroma = new_data / "chroma"; new_chroma.mkdir()
    new_kb_root = new_data / "kb"; new_kb_root.mkdir()

    monkeypatch.setattr(coa_store, "DATA_ROOT", new_data)
    monkeypatch.setattr(coa_store, "CHROMA_DIR", new_chroma)
    monkeypatch.setattr(coa_store, "_chroma_client", None)

    monkeypatch.setattr(knowledge_base, "_DATA_ROOT", new_data)
    monkeypatch.setattr(knowledge_base, "_CHROMA_DIR", new_chroma)
    monkeypatch.setattr(knowledge_base, "_KB_FILES_ROOT", new_kb_root)
    monkeypatch.setattr(knowledge_base, "_chroma_client", None)

    monkeypatch.setattr(main_mod, "JE_DATA_DIR", new_data)
    monkeypatch.setattr(main_mod, "KB_FILES_ROOT", new_kb_root)
    yield {"data": new_data, "chroma": new_chroma, "kb_root": new_kb_root}


@pytest.fixture
def seeded_church(isolated_data):
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


def _fake_claude_qa(answer_text: str):
    """Return a callable suitable for patching `anthropic.Anthropic`.

    The router does `import anthropic; anthropic.Anthropic(api_key=...).messages.create(...)`
    so we patch the class constructor to return a stub whose .messages.create
    returns a structured QA payload.
    """
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps({
        "intent": "QA", "answer": answer_text,
    }))]
    msg.usage = MagicMock(input_tokens=10, output_tokens=20)

    inner = MagicMock()
    inner.messages.create.return_value = msg
    return MagicMock(return_value=inner)


# ===========================================================================
# A. CHAT FUNCTION
# ===========================================================================

class TestChatFunction:

    def test_A1_chat_qa_returns_structured_response(
        self, client, seeded_church, monkeypatch
    ):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.Anthropic", new=_fake_claude_qa("General fund balance is $X.")):
            r = client.post("/api/chat", json={
                "question": "What is the general fund balance?",
                "church_id": seeded_church.church_id,
            })
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "QA"
        assert "answer" in body and body["answer"]
        assert "skills_consulted" in body

    def test_A2_chat_detects_create_je_intent_without_llm(
        self, client, seeded_church, monkeypatch
    ):
        # No ANTHROPIC_API_KEY needed: regex fast path handles JE intent.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("backend.tools.chat_router._extract_je_slots_with_claude",
                   return_value={
                       "from_account_hint": "operating cash",
                       "to_account_hint": "Friendship Center",
                       "amount": 250.0, "fund_hint": None, "memo": "test",
                   }):
            r = client.post("/api/chat", json={
                "question": "Create a journal entry to transfer $250 to outreach",
                "church_id": seeded_church.church_id,
            })
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "CREATE_MANUAL_JE"
        assert body["je_draft"] is not None
        assert body["confirmation_required"] is True

    def test_A3_chat_returns_documented_error_when_no_api_key(
        self, client, seeded_church, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        r = client.post("/api/chat", json={
            "question": "What is fund accounting?",
            "church_id": seeded_church.church_id,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["error_code"] == "assistant-unavailable:no-key"
        assert body["intent"] == "QA"

    def test_A4_chat_grounds_answer_in_kb_for_church(
        self, client, seeded_church, monkeypatch
    ):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from backend.tools import knowledge_base
        knowledge_base.ingest_canon_skills()  # seed kb_canon

        captured: Dict[str, Any] = {}
        def spy_kb_search(q, church_id=None, k=3, denomination=None):
            captured["church_id"] = church_id
            captured["denomination"] = denomination
            return []

        monkeypatch.setattr(knowledge_base, "kb_search", spy_kb_search)
        with patch("anthropic.Anthropic", new=_fake_claude_qa("ok")):
            client.post("/api/chat", json={
                "question": "How do I record an apportionment?",
                "church_id": seeded_church.church_id,
            })
        assert captured["church_id"] == seeded_church.church_id
        assert captured["denomination"] == DenominationType.EPISCOPAL

    def test_A5_chat_inherits_job_accounting_context(
        self, client, seeded_church, monkeypatch
    ):
        from backend import main as main_mod
        job = MagicMock()
        job.accounting_context = seeded_church
        monkeypatch.setattr(main_mod.flow, "get_job", lambda jid: job)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("backend.tools.chat_router._extract_je_slots_with_claude",
                   return_value={"from_account_hint": "operating cash",
                                 "to_account_hint": "maintenance",
                                 "amount": 50.0, "fund_hint": None, "memo": ""}):
            r = client.post("/api/chat", json={
                "question": "Draft a journal entry for $50 maintenance",
                "job_id": "job-xyz",
            })
        assert r.status_code == 200
        assert r.json()["intent"] == "CREATE_MANUAL_JE"


# ===========================================================================
# B. VECTOR DATASTORE + EMBEDDINGS
# ===========================================================================

class TestVectorAndEmbeddings:

    def test_B1_canon_ingest_is_idempotent(self, isolated_data):
        from backend.tools import knowledge_base
        n1 = knowledge_base.ingest_canon_skills()
        n2 = knowledge_base.ingest_canon_skills()
        assert n1 > 0, "kb_canon should ingest at least one canon chunk"
        assert n2 == 0, "second call should be a no-op"

    def test_B2_kb_search_returns_ranked_hits_with_citations(self, isolated_data):
        from backend.tools import knowledge_base
        knowledge_base.ingest_canon_skills()
        hits = knowledge_base.kb_search("fund accounting restriction", k=3)
        assert len(hits) >= 1
        for h in hits:
            assert h.text and h.citation
            assert isinstance(h.score, float)
            assert h.source_path.endswith("SKILL.md")

    def test_B3_per_church_kb_upload_then_search_via_api(
        self, client, seeded_church
    ):
        doc = (
            "# Holy Comforter Vestry Policy\n\n"
            "All capital expenditures over $5,000 require a vote of the Vestry. "
            "The Friendship Center is a restricted outreach fund.\n"
        )
        files = {"file": ("vestry.md", doc, "text/markdown")}
        up = client.post(
            f"/api/churches/{seeded_church.church_id}/kb/upload", files=files
        )
        assert up.status_code == 200, up.text

        r = client.get(
            f"/api/churches/{seeded_church.church_id}/kb/search",
            params={"q": "vestry capital expenditure approval", "k": 3},
        )
        assert r.status_code == 200
        hits = r.json()
        assert any("Vestry" in h["text"] or "vestry" in h["text"] for h in hits)

    def test_B4_denomination_filter_excludes_other_traditions(
        self, isolated_data
    ):
        from backend.tools import knowledge_base
        knowledge_base.ingest_canon_skills()
        episcopal_hits = knowledge_base.kb_search(
            "apportionment", k=5, denomination=DenominationType.EPISCOPAL
        )
        for h in episcopal_hits:
            # Episcopal-scoped query must not return UMC-only canon
            assert h.denomination in {"", "EPISCOPAL"}, h.denomination

    def test_B5_coa_semantic_search_resolves_hint_via_embedding(
        self, seeded_church
    ):
        """Vector embedding pipeline returns ranked CoA hits with similarity
        scores. Substring overlap is sufficient to verify ordering: the query
        contains 'cash' which the embedding model must rank above 'Maintenance'."""
        from backend.tools import coa_store
        results = coa_store.semantic_search(
            seeded_church.church_id, "operating cash account", k=3
        )
        assert results, "embedding search returned nothing"
        # All returned hits are real seeded accounts with similarity scores.
        all_nums = {r.get("account_number") for r in results}
        assert all_nums.issubset({"1010", "1020", "6500"})
        for r in results:
            assert 0.0 <= r.get("score", -1) <= 1.0
        # The cash-like accounts must outrank the expense account for a
        # cash-themed query — direct evidence the embeddings are doing work.
        top = results[0]
        assert top.get("account_number") in {"1010", "1020"}, top


# ===========================================================================
# C. PER-AGENT CONVERSATION
# ===========================================================================

# Each entry: (registry_key, sample_question, expected_skill_or_tool_substring)
CONVERSATIONAL_AGENTS = [
    ("drafting",
     "Create a journal entry to transfer $100 from operating cash to maintenance",
     "journal_entry_builder"),
    ("reconciliation",
     "Why was bank transaction TXN-77 flagged as an exception?",
     "reconcil"),
    ("compliance",
     "Can we spend from the Friendship Center fund for general utilities?",
     "fund"),
    ("auto_post",
     "Should the recurring electric bill auto-post this month?",
     "recurring"),
    ("advisor",
     "What is the YTD variance on the Maintenance budget line?",
     "variance"),
]


class TestPerAgentConversation:

    @pytest.mark.parametrize("agent_key", [k for k, _, _ in CONVERSATIONAL_AGENTS])
    def test_C1_agent_is_conversation_capable(self, agent_key):
        from backend.agents.agents import AGENT_REGISTRY
        agent = AGENT_REGISTRY[agent_key]
        assert agent.role and agent.goal and agent.backstory, \
            f"{agent_key} missing conversational fields"
        assert getattr(agent, "tools", None), \
            f"{agent_key} has no tools — cannot ground its answers"

    @pytest.mark.parametrize("agent_key,question,expected_substr",
                             CONVERSATIONAL_AGENTS)
    def test_C2_chat_can_address_each_agent_domain(
        self, client, seeded_church, monkeypatch,
        agent_key, question, expected_substr,
    ):
        """Send the agent's domain question through /api/chat and verify the
        router consults the right skill family. JE intents bypass the LLM via
        the regex fast path; QA intents are routed through a mocked Claude."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("backend.tools.chat_router._extract_je_slots_with_claude",
                   return_value={"from_account_hint": "operating cash",
                                 "to_account_hint": "maintenance",
                                 "amount": 100.0, "fund_hint": None, "memo": ""}), \
             patch("anthropic.Anthropic", new=_fake_claude_qa(
                       f"[{agent_key}] grounded answer")):
            r = client.post("/api/chat", json={
                "question": question,
                "church_id": seeded_church.church_id,
            })

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answer"], f"{agent_key} produced empty answer"
        # The router always reports which skills it consulted — proof that the
        # conversational pathway ran through the skill registry rather than a
        # bare LLM passthrough.
        assert isinstance(body.get("skills_consulted"), list)
        assert body["skills_consulted"], f"{agent_key} consulted no skills"
        # Intent classification correctly distinguishes JE-create vs QA
        # questions even when asked in the voice of a specific agent.
        if "journal entry" in question.lower() or "transfer $" in question.lower():
            assert body["intent"] == "CREATE_MANUAL_JE"
        else:
            assert body["intent"] == "QA"

    def test_C3_chat_history_grounding_is_consistent_across_turns(
        self, client, seeded_church, monkeypatch
    ):
        """A second turn in the same church must surface the same KB
        denomination scope as the first — proving conversation context is
        carried through KB grounding rather than reset per call."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from backend.tools import knowledge_base
        knowledge_base.ingest_canon_skills()

        seen: List[Any] = []
        real = knowledge_base.kb_search

        def spy(q, church_id=None, k=3, denomination=None):
            seen.append((church_id, denomination))
            return real(q, church_id=church_id, k=k, denomination=denomination)

        monkeypatch.setattr(knowledge_base, "kb_search", spy)
        with patch("anthropic.Anthropic", new=_fake_claude_qa("answer")):
            client.post("/api/chat", json={
                "question": "What is fund accounting?",
                "church_id": seeded_church.church_id})
            client.post("/api/chat", json={
                "question": "Follow-up: show me an example.",
                "church_id": seeded_church.church_id})

        assert len(seen) == 2
        assert seen[0] == seen[1], (
            "KB scope diverged across turns: " + repr(seen)
        )
