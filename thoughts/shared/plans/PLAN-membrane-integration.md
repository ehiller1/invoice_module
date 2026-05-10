# PLAN: EIME → Embark Membrane-Governed Multi-Domain Architecture Integration

**Document ID:** PLAN-membrane-integration
**Created:** 2026-05-07
**Author:** architect-agent
**Project Root:** `/Users/erichillerbrand/chart of accounts/`
**Source Specs:** `/tmp/invoice_membrane_review/EIME_Membrane_Integration_Requirements_v1.docx`, `registry-additions-UPDATED.xlsx`, `INTEGRATION_SUMMARY.txt`
**Target Effort (v1):** ~58 person-days across 11 phases (phase 12 deferred)

---

## 1. Executive Summary

### What is being migrated and why

The Embark Invoice Mapping Engine (EIME) is currently a self-contained FastAPI application that processes church invoices end-to-end: PDF ingestion, GL mapping, fund-restriction validation, dual approval, ACS Realm posting, payment generation (NACHA/check/CC), reconciliation, and recurring entry handling. It functions as a single-domain accounting tool.

The Embark Membrane-Governed Multi-Domain Architecture is a broader platform vision in which **Accounting** is one of several governed domains (Stewardship, Pastoral Care, etc.) that exchange information through a **Membrane** — a translation-and-governance boundary that distills internal reasoning, redacts privacy-sensitive fields, and routes signals through a six-position **Guider Cascade** before publishing them on a **Redis event mesh**.

This migration retrofits EIME with the membrane substrate so that it can:

1. **Emit typed perturbations** (10 signals, IDs 59–68) at well-defined pipeline points instead of just writing to local state.
2. **Persist authoritative state as Cards** (9 types) instead of ad-hoc JSON files.
3. **Route decisions through guider cascade** (accounting-integrity, payment-dedup, polity-and-deference, abundance-and-stewardship, witness-and-provenance, dignity).
4. **Expose long-running work as CrewAI Flows** with suspend/resume semantics for HITL gates.
5. **Maintain full provenance** through an immutable Decision Ledger and Episode Memory.

### Scope

**Preserved unchanged:** the inner pipeline mechanics — `pdf_extractor.py`, `classifier.py`, `gl_mapper.py`, `budget_comparator.py`, `journal_builder.py`, `nacha_generator.py`, `check_generator.py`, `cc_generator.py`, ACS Realm Playwright automation, ChromaDB stores, the 9-step setup wizard, RBAC roles. The inner business logic is correct and battle-tested.

**Added:** governance, communication, and persistence layers — perturbation emitters, ImpactSignal envelope schema, Outer Membrane (Distiller / Redactor / Publisher), six-position Guider Cascade, Redis event mesh (Streams + Pub/Sub), Card Store (replaces internal job records), Decision Ledger, Episode Memory, CrewAI Flow integration for HITL.

**Refactored (not rewritten):** `backend/flow.py` becomes a thin orchestrator that wraps existing tools with perturbation emission and cascade traversal. `backend/main.py` continues serving HTTP, but new endpoints emit signals; existing endpoints are dual-write during transition.

**Deferred to v2:** Receptor for inbound Stewardship amendments (FR-IM-13 v2).

### Risk profile

| Risk | Severity | Notes |
|------|----------|-------|
| Q-5 GL→budget-owner mapping unspecified | **Blocker** | Phase 8 cannot ship without seed data from Matt Babcock |
| Redis operational complexity | Medium | Mitigated by Redis Stack docker-compose for dev; managed Redis (Upstash/Elasticache) for prod |
| Dual-write divergence (JSON vs Cards) | Medium | Mitigated by checksum reconciliation job during transition window |
| CrewAI Flow / FastAPI coexistence | Low | Flow runs out-of-process; FastAPI delegates long-running ops via Flow run handles |
| Schema drift across services | Medium | Mitigated by `jsonschema` validation at every publish/consume |
| Privacy class regression (P3 leakage) | **High** | Mitigated by Redactor unit tests + privacy audit ledger + integration test gates |

### Estimated effort (v1)

| Phase | Effort (person-days) |
|-------|----------------------|
| 1. Foundation                       | 5 |
| 2. Transport (Redis)                | 4 |
| 3. Skill Library                    | 10 |
| 4. Guiders                          | 6 |
| 5. Core Pipeline Migration          | 5 |
| 6. HITL Gate                        | 4 |
| 7. Membrane Wiring                  | 4 |
| 8. Approval + Posting               | 4 |
| 9. Reconciliation + Payment Dedup   | 3 |
| 10. Cards + Ledger                  | 7 |
| 11. Tests                           | 6 |
| **Total v1**                        | **58** |
| 12. v2 Receptor (Stewardship in)    | DEFERRED |

### Critical dependencies / blockers

1. **Q-5 (BLOCKER for Phase 8):** GL-to-budget-owner mapping seed data must come from Matt Babcock before authority routing can be tested end-to-end. Workaround: ship Phase 8 with a stub mapping table behind a feature flag.
2. **Q-IM-1:** Pseudonym table rotation policy (cadence + key-storage). Required before Phase 7 ships to a tenant.
3. **Q-IM-2:** Confirmation that Episode Cards finalize at 6 weeks (vs. 4 or 8). Affects Phase 10 retention logic.
4. **Q-IM-3:** `trace_id` propagation strategy across Cowork (Stewardship) boundary. Affects Phase 10 ledger schema.
5. **Q-IM-4:** Stewardship amendment schema (v2 receptor).

---

## 2. Current State Audit

### EIME → Code Map (FR-01 through FR-10)

| Existing FR | Capability | Where it lives | Disposition |
|------|------------|----------------|-------------|
| FR-01 | PDF ingestion | `backend/tools/pdf_extractor.py`, `backend/tools/file_text_extractor.py`, `backend/uploads/` | **Preserve** — wrap with `INVOICE_INGESTED` emitter |
| FR-02 | Line-item classification | `backend/tools/classifier.py` | **Preserve** — wrap with skill SKILL.md |
| FR-03 | GL account mapping | `backend/tools/gl_mapper.py`, `backend/tools/coa_store.py` (ChromaDB) | **Preserve** — wrap; emit `MAPPING_CONFIDENCE_LOW` |
| FR-04 | Budget comparison | `backend/tools/budget_comparator.py`, `backend/tools/budget_projector.py` | **Preserve** — emit `BUDGET_OVERAGE_RISK` |
| FR-05 | Fund restriction validation | `backend/tools/denomination_rules.py`, ChromaDB canon collection | **Preserve** — emit `FUND_RESTRICTION_VIOLATION` (HARD BLOCK) |
| FR-06 | Approval routing | `backend/tools/approval_chain_resolver.py`, `backend/tools/budgetary_authority.py`, `backend/auth.py` | **Refactor** — replace with cascade `polity-and-deference` |
| FR-07 | Journal entry build | `backend/tools/journal_builder.py`, `backend/tools/je_state.py`, `backend/tools/je_csv_importer.py` | **Preserve** — emit `JOURNAL_ENTRY_READY` |
| FR-08 | ACS Realm posting | `backend/integrations/acs_realm/` (Playwright, selectors.yaml) | **Preserve** — gate behind cascade `BLOCK` checks |
| FR-09 | Payment generation | `backend/tools/nacha_generator.py`, `check_generator.py`, `cc_generator.py`, `payment_recommender.py` | **Preserve** — emit `PAYMENT_DEDUP_RISK` (HARD BLOCK) |
| FR-10 | Reconciliation | `backend/integrations/plaid_client.py`, `backend/tools/plaid_store.py`, `backend/tools/bank_statement_parser.py` | **Preserve** — emit `RECONCILIATION_EXCEPTION` |

### Cross-cutting capabilities

| Capability | Where it lives | Disposition |
|------------|----------------|-------------|
| RBAC | `backend/auth.py` (TREASURER_ADMIN / BUDGET_OWNER / FINANCE_STAFF) | **Preserve** — feeds polity-and-deference guider |
| Audit log (SHA-256 chain) | `backend/tools/approval_audit.py` | **Refactor** — becomes Decision Ledger writer |
| Recurring JE | `backend/tools/recurring_store.py` | **Preserve** |
| Risk assessment | `backend/tools/risk_assessor.py`, `risk_summary.py`, `fraud_detector.py` | **Preserve** — feeds Risk Card writes |
| Setup wizard | `backend/setup_wizard.py`, `frontend/` 9-step UI | **Preserve** |
| Scheduler | `backend/scheduler.py` (APScheduler) | **Preserve** — emits `APPROVAL_DEADLINE_PRESSURE` |
| Skill scaffolding | `backend/skills/{orchestrator,worker,researcher,reviewer,membrane,conversationalist}/` | **Extend** — author the 19 SKILL.md packages here |

### What is missing entirely

| Missing component | FR-IM Reference | Notes |
|-------------------|-----------------|-------|
| Perturbation registry & emitter | FR-IM-02, FR-IM-03 | New `backend/membrane/perturbations.py` |
| ImpactSignal envelope schema | FR-IM-03 | New `backend/membrane/schemas/impact_signal_v1.json` |
| Outer Membrane (Distiller / Redactor / Publisher) | FR-IM-04 | Only ACS Realm distiller exists; need general-purpose |
| 6-position Guider Cascade | FR-IM-05 | None of the 6 guiders exist as cascade plugins |
| Redis event mesh | FR-IM-06 | No Redis dep currently; in-process FastAPI only |
| Card Store | FR-IM-07 | State currently in JSON files under `backend/data/` |
| Decision Ledger (Decision Packet schema) | FR-IM-11 | Partial: `approval_audit.py` has hash chain but not Decision Packet schema |
| Episode Memory | FR-IM-11 | Does not exist |
| Privacy class enforcement (field-level) | FR-IM-08 | RBAC exists; field-level redaction does not |
| CrewAI Flow with suspend/resume | FR-IM-10 | Currently FastAPI request/response only |
| Status narration channel | FR-IM-14 | UI gets state via REST polling; no Pub/Sub channel |

### What needs refactoring (not rewriting)

| File | Refactor type |
|------|---------------|
| `backend/flow.py` | Becomes orchestrator wrapper that emits perturbations and consults cascade |
| `backend/tools/approval_audit.py` | Adds Decision Packet schema; preserves SHA-256 chain |
| `backend/tools/approval_chain_resolver.py` | Becomes input to polity-and-deference guider |
| `backend/main.py` | New endpoints emit signals; existing endpoints dual-write to Cards |
| `backend/integrations/acs_realm/playwright_runner.py` | Add cascade-veto check before posting |

---

## 3. Architecture Decisions

### AD-1: Storage migration (JSON files → Cards) is **phased and dual-write**

- Phase 10 introduces `backend/cards/store.py` with a `CardStore` interface backed initially by SQLite (sufficient for v1 single-tenant) with a Postgres adapter ready behind an interface seam.
- During the transition window (Phase 10 → end of Phase 11), every state mutation writes to **both** the legacy JSON file and the Card Store. A reconciliation job (`backend/cards/reconcile.py`) runs nightly and reports drift.
- Cutover criterion: 14 consecutive days of zero drift across all 6 EIME-written card types. Then JSON writers are deleted; readers switch to Cards.

### AD-2: Redis deployment

- **Dev:** Redis Stack 7.4 via `docker-compose.yml` at repo root. Includes RedisJSON + RediSearch (used for Card Store secondary indexes if we later promote SQLite → Redis-backed).
- **Sandbox/Prod:** Managed Redis (Upstash recommended for low ops; Elasticache fallback). Required modules: Streams, Pub/Sub. RedisJSON optional.
- Connection abstracted behind `backend/membrane/transport/redis_client.py`. Uses `redis-py` async client.

### AD-3: CrewAI Flow ↔ FastAPI coexistence

- FastAPI continues to be the **HTTP surface** (existing endpoints + new ones).
- CrewAI Flows handle long-running, suspendable orchestration (`invoice_processing_workflow`). Flows run in a worker process started alongside uvicorn.
- FastAPI endpoints that initiate long-running work return a `flow_run_id`; clients poll a `/flows/{run_id}` endpoint or subscribe to the `processing_status` Pub/Sub channel for updates.
- Flow suspend/resume backed by Card Store (a Flow run is itself an Episode Card with `status=suspended` and a resumption token).

### AD-4: Skill library transition is **additive**

- Existing `backend/tools/*.py` modules continue to exist and are still imported.
- For each tool, we add a sibling `backend/skills/<archetype>/<name>/SKILL.md` that documents the skill contract (inputs, outputs, privacy class, perturbations emitted). The Python entrypoint inside the skill folder calls into the existing tool.
- A `backend/skills/registry.py` (extending the existing `tools/skill_registry.py`) loads SKILL.md frontmatter at startup. Tools that have a SKILL.md package are routed through the skill router; tools without a package continue working as before.
- Deprecation: tools become thin shims after their SKILL package is feature-complete. No big-bang rewrite.

### AD-5: Schema versioning

- `ImpactSignal` envelope is **v1** (`schema_version: "1.0"`). Future versions add fields with default values; consumers must accept additive changes.
- Cards carry a `revision` integer (optimistic locking) and a `schema_version` (for migrations). Card schema is per-type and lives in `backend/cards/schemas/`.
- Breaking schema changes require a major bump and dual-publish window.

### AD-6: Backward compatibility

- Every existing API endpoint continues to work for at least 2 sprints after Phase 5 lands.
- New endpoints are added under `/v2/` namespace where semantics differ (e.g., `/v2/invoices/{id}/process` is Flow-backed and emits signals; `/invoices/{id}/process` continues to exist).
- Feature flags per FR-IM (in `backend/membrane/feature_flags.py`) allow disabling each membrane capability independently for rollback.

### AD-7: Privacy enforcement layer placement

- The **Redactor** runs after the Distiller and before the Publisher. It is the only component with `WRITE` access to the privacy audit ledger. Pseudonym lookups are sourced from a `PseudonymTable` with rotating keys.
- The **CardStore** invokes a privacy validator on every write to prevent stowing P3 fields in P0/P1 cards.
- P3 detection failures are **fatal**: the publisher refuses to emit; the writer raises `PrivacyClassViolation`; an alert lands in the dead-letter channel.

### AD-8: Idempotency

- Every signal carries a `signal_id` (UUIDv7). Consumers maintain a 24-hour dedup window (Redis SET with TTL).
- Hard-block perturbations (62, 68) are idempotent on retry: if blocked once, retrying the same signal yields the same blocked decision until the underlying card mutates.

---

## 4. Implementation Phases

### Phase 1 — Foundation (5 person-days)

**Goal:** Add perturbation registry, ImpactSignal envelope schema, and a reusable Distiller core so subsequent phases have a stable substrate.

**FR-IM References:** FR-IM-02, FR-IM-03, FR-IM-04 (partial, distiller only)

**Tasks:**
- Implement perturbation registry with the 10 signals (IDs 59–68): name, privacy class, `crosses_membrane`, default retention, target channel.
- Author JSON Schema for `ImpactSignal` envelope (v1) and load it at startup.
- Implement `ImpactSignal` Pydantic model that validates against the schema on construction.
- Implement `Distiller` base class with one method `distill(internal_state) -> DistilledPayload`; subclasses override per signal.
- Add `backend/membrane/__init__.py` package skeleton.

**Files to Create:**
- `backend/membrane/perturbations.py` — registry of 10 signals
- `backend/membrane/schemas/impact_signal_v1.json` — JSON Schema
- `backend/membrane/envelope.py` — `ImpactSignal` Pydantic model
- `backend/membrane/distiller/base.py` — `Distiller` base class
- `backend/membrane/distiller/__init__.py`
- `backend/membrane/feature_flags.py` — per-FR-IM toggles

**Files to Modify:**
- `pyproject.toml` — add `jsonschema>=4.23`, `uuid7>=0.1`

**Dependencies:** none

**Verification Criteria:**
- `pytest backend/tests/test_phase1_envelope.py` passes; covers schema-valid and schema-invalid signals.
- Each of the 10 perturbations has a test that constructs and validates a sample signal.
- Privacy class for each perturbation matches the spec (P0 only for ID 63; rest P1).

**Risks:** Schema-version drift if v1 not frozen carefully. Mitigation: pin v1 in `schemas/` and gate changes by code review.

---

### Phase 2 — Transport: Redis Event Mesh (4 person-days)

**Goal:** Stand up Redis (dev + prod-ready) and ship Publisher / Consumer modules wired to the 13 channels.

**FR-IM References:** FR-IM-06

**Tasks:**
- Add Redis Stack to `docker-compose.yml` with persistent volume.
- Define 13 channels in `backend/membrane/transport/channels.py` (3 cross-domain Streams, 7 internal Streams, 1 advisory Pub/Sub, 2 infrastructure Streams).
- Implement `Publisher` (publishes ImpactSignal to the right channel; 2-attempt retry; on final failure routes to dead-letter Stream).
- Implement `Consumer` base class (consumer-group semantics for Streams; `XREADGROUP` + ack pattern; idempotency dedup).
- Implement health check endpoint `/health/redis`.
- Add `REDIS_URL`, `MEMBRANE_ENV` envvars to `.env.example` and `backend/main.py` startup.

**Files to Create:**
- `docker-compose.yml` (root)
- `backend/membrane/transport/redis_client.py`
- `backend/membrane/transport/channels.py`
- `backend/membrane/transport/publisher.py`
- `backend/membrane/transport/consumer.py`
- `backend/membrane/transport/dead_letter.py`
- `backend/tests/test_phase2_transport.py`

**Files to Modify:**
- `pyproject.toml` — add `redis>=5.2`, `redis[hiredis]`
- `backend/main.py` — startup hook initializes Redis client + verifies streams
- `.env.example` (create if missing)

**Dependencies:** Phase 1 (envelope is published)

**Verification Criteria:**
- Round-trip test: publish a sample `INVOICE_INGESTED` and consume it via a test consumer group within 1s.
- Dead-letter test: simulate publish failure → message lands in `infra:dead_letter` Stream.
- Idempotency test: publish same `signal_id` twice; consumer processes once.

**Risks:** Redis memory growth from un-trimmed streams. Mitigation: `MAXLEN ~ 100000` per stream, monitored.

---

### Phase 3 — Skill Library (10 person-days)

**Goal:** Author 19 `SKILL.md` packages and a skill router; integrate with CrewAI Flow.

**FR-IM References:** FR-IM-01

**Tasks:**
- Author SKILL.md frontmatter spec (archetype, inputs, outputs, privacy_class, perturbations_emitted, depends_on).
- Author 19 SKILL.md packages (existing scaffolds in `backend/skills/` get filled in; missing ones are created):
  - **Orchestrator (1):** `invoice_processing_workflow` (already scaffolded; fill in)
  - **Researcher (2 + 3 denom):** `coa_reference_loader`, `vendor_history_lookup`, `denomination_rules/{episcopal,methodist,baptist}` (existing scaffolds: `denomination_baptist`, `denomination_catholic_parish`, `denomination_episcopal`, `denomination_presbyterian`, `denomination_umc` — keep these as the denomination-rules sub-skills)
  - **Worker (8):** `pdf_extraction`, `line_item_classifier`, `gl_account_mapper`, `journal_entry_builder`, `credit_memo_handler`, `payment_matching`, `ach_file_generator`, `recurring_je_drafter`
  - **Reviewer (2):** `allocation_reviewer`, `restriction_validator`
  - **Conversationalist (1):** `hitl_invoice_gate`
  - **Membrane (1):** `accounting_domain_distillation`
  - **Receptor (1, scaffold only):** `stewardship_amendment_receiver` (skeleton; v2 deferred)
- Implement `backend/skills/registry.py` that walks the skills tree, loads SKILL.md frontmatter, and exposes a `resolve(name) -> SkillPackage` function.
- Implement `backend/skills/router.py` that dispatches a skill invocation through the right archetype handler.
- Wire CrewAI Flow: implement `invoice_processing_workflow` Flow that calls skills in sequence.

**Files to Create:**
- 19 × `SKILL.md` files (some directories already exist; add `SKILL.md` + `entry.py` to each)
- `backend/skills/registry.py`
- `backend/skills/router.py`
- `backend/skills/orchestrator/invoice_processing_workflow/flow.py` (CrewAI Flow class)
- `backend/tests/test_phase3_skills.py`

**Files to Modify:**
- `backend/tools/skill_registry.py` — extend to consume new registry
- `pyproject.toml` — confirm `crewai` version supports Flow API

**Dependencies:** Phase 1 (skills emit perturbations through registry)

**Verification Criteria:**
- All 19 SKILL.md files load without schema validation errors.
- `invoice_processing_workflow` Flow executes end-to-end on a sample invoice in dry-run mode (no posting).
- Skill router resolves all skills by name.

**Risks:** CrewAI Flow API churn. Mitigation: pin `crewai` version; provide thin abstraction layer in `backend/membrane/flow_adapter.py` so we can swap orchestrators if needed.

---

### Phase 4 — Guiders (6 person-days)

**Goal:** Implement 2 new guiders (`accounting-integrity`, `payment-dedup`); wire 4 reused Core Seven guiders into the cascade.

**FR-IM References:** FR-IM-05

**Tasks:**
- Define `Guider` base class with `evaluate(signal, context) -> GuiderVerdict` where verdict ∈ {PASS, ANNOTATE, BLOCK, ESCALATE, DEFER}.
- Implement `accounting-integrity` (position 1): balance check (debits=credits), restriction check (uses `denomination_rules.py`), dual-approval invariant (uses `budgetary_authority.py`).
- Implement `payment-dedup` (position 2): hashes (vendor_id, invoice_no, amount, due_date) into a Bloom filter + Card-backed dedup table; checks Vanco + ACH simultaneously.
- Wire `polity-and-deference` (position 3): consults `approval_chain_resolver.py` and `auth.py` for authority routing.
- Wire `abundance-and-stewardship` (position 4): annotates `BUDGET_OVERAGE_RISK` with anti-scarcity framing.
- Wire `witness-and-provenance` (position 5): validates canon citations on FUND_RESTRICTION_VIOLATION; reads ChromaDB canon collection.
- Wire `dignity` (position 6): inspects clergy comp lines and vulnerable-party fields; blocks P3 leakage.
- Implement `Cascade` runner that executes guiders in order; first BLOCK stops; ANNOTATE accumulates; ESCALATE/DEFER short-circuits to HITL.

**Files to Create:**
- `backend/membrane/guiders/__init__.py`
- `backend/membrane/guiders/base.py`
- `backend/membrane/guiders/accounting_integrity.py`
- `backend/membrane/guiders/payment_dedup.py`
- `backend/membrane/guiders/polity_and_deference.py`
- `backend/membrane/guiders/abundance_and_stewardship.py`
- `backend/membrane/guiders/witness_and_provenance.py`
- `backend/membrane/guiders/dignity.py`
- `backend/membrane/cascade.py`
- `backend/tests/test_phase4_guiders.py`

**Files to Modify:**
- `backend/tools/budgetary_authority.py` — expose authority lookup function consumable by cascade
- `backend/tools/approval_chain_resolver.py` — expose chain resolver as a pure function

**Dependencies:** Phase 1, Phase 3 (cascade is invoked from skills)

**Verification Criteria:**
- Each guider has unit tests for at least 3 verdict types.
- Cascade test: a `FUND_RESTRICTION_VIOLATION` signal produces BLOCK with the expected reason.
- Cascade test: a `BUDGET_OVERAGE_RISK` signal produces ANNOTATE + ESCALATE (cross-domain to Stewardship).

**Risks:** Bloom filter false positives in payment-dedup. Mitigation: Bloom is first-stage filter; positive hit triggers Card-backed exact lookup before BLOCK.

---

### Phase 5 — Core Pipeline Migration (5 person-days)

**Goal:** Wire perturbation emissions into the existing pipeline at the 10 well-defined points without rewriting business logic.

**FR-IM References:** FR-IM-02 (full), FR-IM-15 (start)

**Tasks:**
- Identify the 10 emission points in `backend/flow.py` and surrounding tools:
  1. After PDF extraction → `INVOICE_INGESTED` (id 59)
  2. After GL mapper if confidence < threshold → `MAPPING_CONFIDENCE_LOW` (id 60)
  3. After budget comparator if overage → `BUDGET_OVERAGE_RISK` (id 61)
  4. After denomination_rules check → `FUND_RESTRICTION_VIOLATION` (id 62)
  5. After journal_builder → `JOURNAL_ENTRY_READY` (id 63)
  6. On HITL trigger → `HITL_ESCALATION` (id 64)
  7. On HITL response → `HITL_DECISION_RETURNED` (id 65)
  8. From scheduler when SLA at risk → `APPROVAL_DEADLINE_PRESSURE` (id 66)
  9. After plaid reconciliation if exception → `RECONCILIATION_EXCEPTION` (id 67)
  10. Before payment generation if dedup hit → `PAYMENT_DEDUP_RISK` (id 68)
- Add emission calls (each one liner: `await publisher.publish(...)`) at each point.
- Build emissions behind feature flag `MEMBRANE_PERTURBATIONS_ENABLED` so we can disable instantly.
- Confirm existing tests still pass (no behavior change with flag off).

**Files to Modify:**
- `backend/flow.py` — add emission calls at orchestration boundaries
- `backend/tools/pdf_extractor.py` — emit `INVOICE_INGESTED` on success
- `backend/tools/gl_mapper.py` — emit `MAPPING_CONFIDENCE_LOW`
- `backend/tools/budget_comparator.py` — emit `BUDGET_OVERAGE_RISK`
- `backend/tools/denomination_rules.py` — emit `FUND_RESTRICTION_VIOLATION`
- `backend/tools/journal_builder.py` — emit `JOURNAL_ENTRY_READY`
- `backend/scheduler.py` — emit `APPROVAL_DEADLINE_PRESSURE`
- `backend/tools/plaid_store.py` — emit `RECONCILIATION_EXCEPTION`
- `backend/tools/payment_recommender.py` (or upstream of nacha_generator) — emit `PAYMENT_DEDUP_RISK`

**Files to Create:**
- `backend/tests/test_phase5_emissions.py`

**Dependencies:** Phase 1, Phase 2

**Verification Criteria:**
- For each of the 10 perturbations, an integration test triggers it and confirms it lands on the correct Redis Stream.
- Existing pipeline tests (`backend/tests/test_phase1_pipeline.py`, etc.) still pass.

**Risks:** Sync→async refactor around emission points. Mitigation: emission is fire-and-forget queued in a background task if the call site is sync.

---

### Phase 6 — HITL Conversational Gate (4 person-days)

**Goal:** Implement `hitl_invoice_gate` skill with CrewAI Flow suspend/resume; add notification dispatcher.

**FR-IM References:** FR-IM-10

**Tasks:**
- Build `hitl_invoice_gate` skill: suspends the Flow, writes an Episode Card with `status=awaiting_human`, sends notification (email via `backend/integrations/email/`).
- Build resumption endpoint `POST /v2/hitl/{flow_run_id}/decision` that: validates signed token, writes `HITL_DECISION_RETURNED` signal, resumes the suspended Flow.
- Build notification dispatcher: email + (future) Slack. Email template uses Jinja2.
- Persist conversation transcript on the Episode Card (HITL turns).

**Files to Create:**
- `backend/skills/conversationalist/hitl_invoice_gate/SKILL.md`
- `backend/skills/conversationalist/hitl_invoice_gate/entry.py`
- `backend/membrane/hitl/dispatcher.py`
- `backend/membrane/hitl/templates/escalation_email.j2`
- `backend/membrane/hitl/resume.py`
- `backend/tests/test_phase6_hitl.py`

**Files to Modify:**
- `backend/main.py` — add `/v2/hitl/{flow_run_id}/decision` route
- `backend/integrations/email/` — confirm SMTP token logic still works for HITL signed tokens

**Dependencies:** Phase 3 (Flow integration), Phase 4 (cascade triggers escalation)

**Verification Criteria:**
- E2E test: low-confidence invoice triggers HITL → email is sent → operator clicks link → Flow resumes → posting completes.
- Resumption-token replay attack test: re-using the same token after consumption is rejected.

**Risks:** Tokens leaking via email forwarding. Mitigation: short TTL (24h), one-time use, includes flow_run_id binding.

---

### Phase 7 — Membrane Wiring (Distiller → Redactor → Publisher) (4 person-days)

**Goal:** Wire end-to-end membrane emission flow inside `backend/flow.py`: internal state → Distiller → Redactor → Cascade → Publisher.

**FR-IM References:** FR-IM-04, FR-IM-05 (full), FR-IM-08

**Tasks:**
- Implement `Redactor` with privacy class enforcement: pseudonymize P1 vendor_id, drop P2 fields, raise on P3.
- Implement `PseudonymTable` with key rotation hooks (key id stamped on each pseudonym).
- Implement privacy audit ledger writer (every redaction event recorded).
- Connect pipeline: when an emitter wants to publish, it calls `membrane.emit(internal_state, perturbation_id)` which:
  1. Selects `Distiller` for that perturbation
  2. Calls `redactor.redact(distilled_payload)`
  3. Calls `cascade.run(redacted_payload, signal_meta)`
  4. If verdict ≠ BLOCK, calls `publisher.publish(envelope)`
  5. If verdict ∈ {ESCALATE, DEFER}, also writes Episode Card and notifies HITL.

**Files to Create:**
- `backend/membrane/redactor/__init__.py`
- `backend/membrane/redactor/pseudonym_table.py`
- `backend/membrane/redactor/privacy_audit.py`
- `backend/membrane/emit.py` — top-level `emit()` function (the public API)
- `backend/membrane/distiller/accounting.py` — concrete distillers per perturbation
- `backend/tests/test_phase7_membrane.py`

**Files to Modify:**
- `backend/flow.py` — replace direct emission calls with `membrane.emit()`
- `backend/skills/membrane/accounting_domain_distillation/entry.py` — wire to distiller core

**Dependencies:** Phases 1, 2, 4

**Verification Criteria:**
- P3 leakage test: attempting to emit a payload containing a P3 field raises `PrivacyClassViolation` and is logged in audit.
- Pseudonym determinism test: same vendor_id → same pseudonym within a key epoch.
- Pseudonym rotation test: after key rotation, new pseudonyms are issued; old ones remain decoded by audit.

**Risks:** Pseudonym table corruption. Mitigation: append-only file + nightly checksum.

---

### Phase 8 — Approval + Posting (ACS Realm) (4 person-days)

**Goal:** Route approvals through `polity-and-deference` cascade; gate ACS Realm posting on cascade verdict.

**FR-IM References:** FR-IM-09

**Tasks:**
- Replace direct calls to `approval_chain_resolver.py` with cascade traversal: cascade returns the approver chain.
- Add cascade veto check before invoking ACS Realm playwright runner.
- Implement dual-approval invariant: signals carrying `requires_dual_approval=true` (from accounting-integrity) cannot proceed until two distinct approvers (with different roles) have approved.
- Update Decision Packet schema with cascade_verdict, approver_chain, signed approvals.

**Files to Create:**
- `backend/membrane/approval/router.py`
- `backend/membrane/approval/dual_approval.py`
- `backend/tests/test_phase8_approval.py`

**Files to Modify:**
- `backend/integrations/acs_realm/acs_actions.py` — call `cascade.allows_post(je_id)` before posting
- `backend/main.py` — `/v2/approvals/{id}/approve` route emits signal and goes through cascade
- `backend/tools/budgetary_authority.py` — return structured authority records consumable by cascade

**Dependencies:** Phase 4 (polity-and-deference), Phase 7 (membrane)

**Verification Criteria:**
- E2E test: a $4,200 invoice routes to TREASURER_ADMIN + BUDGET_OWNER (dual approval) and posts to ACS only after both approve.
- Veto test: cascade BLOCK on `FUND_RESTRICTION_VIOLATION` prevents ACS posting.

**BLOCKER:** Q-5 (GL→budget-owner mapping) seed data from Matt Babcock. Workaround: ship behind feature flag; default mapping table lives in `backend/data/gl_owner_mapping.stub.json` with placeholder ownership.

**Risks:** Stale playwright selectors; Matt Babcock data delay.

---

### Phase 9 — Reconciliation + Payment Dedup (3 person-days)

**Goal:** Wire `payment-dedup` guider into payment generation; emit `RECONCILIATION_EXCEPTION` on plaid mismatch.

**FR-IM References:** FR-IM-02 (id 67, 68 emissions)

**Tasks:**
- Add dedup pre-check at every payment generation entry point (NACHA, check, CC).
- Implement Card-backed dedup table (DedupCard? or Risk Card sub-type) with TTL.
- Wire reconciliation exception emission from `plaid_store.py` when a transaction can't match a posted JE within tolerance.

**Files to Create:**
- `backend/membrane/payments/dedup_table.py`
- `backend/tests/test_phase9_dedup.py`

**Files to Modify:**
- `backend/tools/payment_recommender.py` — call dedup guider before recommending payment
- `backend/tools/nacha_generator.py`, `check_generator.py`, `cc_generator.py` — refuse to generate if cascade BLOCK
- `backend/tools/plaid_store.py` — emit reconciliation exception on threshold breach

**Dependencies:** Phase 4 (payment-dedup guider), Phase 7

**Verification Criteria:**
- Double-payment test: same invoice paid via Vanco + ACH within window → second attempt blocked with `PAYMENT_DEDUP_RISK`.
- Reconciliation gap test: posted JE with no matching plaid transaction after N days → `RECONCILIATION_EXCEPTION` emitted.

**Risks:** False positives on legitimate split payments. Mitigation: dedup key includes amount + reference; partial payments are allowed by design.

---

### Phase 10 — Cards + Decision Ledger + Episode Memory (7 person-days)

**Goal:** Migrate state from JSON files to Cards; implement Decision Ledger and Episode Memory.

**FR-IM References:** FR-IM-07, FR-IM-11, FR-IM-12

**Tasks:**
- Define schemas for the 6 EIME-written card types (Risk, Episode, Context Pack, Memory, Decision Packet, Signal Memory) and 1 read-only (Plan).
- Implement `CardStore` with optimistic locking (revision integer; CAS update).
- Implement Decision Ledger: append-only log of Decision Packets; preserves SHA-256 chain from existing `approval_audit.py`.
- Implement Episode Memory: an Episode Card per invoice processing run; finalized at 6 weeks (Q-IM-2 to confirm).
- Implement dual-write shim: every existing JSON state mutation also writes to Card Store.
- Implement reconciliation job (`backend/cards/reconcile.py`) that detects drift between JSON and Cards.
- Implement Episode Memory retrieval API for HITL UI to show prior similar episodes.

**Files to Create:**
- `backend/cards/__init__.py`
- `backend/cards/store.py` (CardStore interface + SQLite impl)
- `backend/cards/schemas/risk_card.json`
- `backend/cards/schemas/episode_card.json`
- `backend/cards/schemas/context_pack.json`
- `backend/cards/schemas/memory_card.json`
- `backend/cards/schemas/decision_packet.json`
- `backend/cards/schemas/signal_memory.json`
- `backend/cards/schemas/plan_card.json` (read-only)
- `backend/cards/ledger.py` — Decision Ledger writer
- `backend/cards/episode.py` — Episode Memory facade
- `backend/cards/reconcile.py` — drift detection job
- `backend/cards/dual_write.py` — shim
- `backend/tests/test_phase10_cards.py`

**Files to Modify:**
- `backend/tools/approval_audit.py` — wraps Decision Ledger
- `backend/tools/je_state.py` — dual-writes to Memory Card
- `backend/tools/risk_summary.py` — dual-writes to Risk Card
- `backend/main.py` — `/v2/episodes/{id}` endpoints

**Dependencies:** Phases 1, 2 (signals reference card_ids), Phase 7 (privacy validation on write)

**Verification Criteria:**
- Optimistic locking test: concurrent updates on same card detect conflict.
- Decision Ledger tamper test: modifying a packet breaks the SHA-256 chain.
- Drift reconciliation: after 1 week of dual-write, drift report shows 0 mismatches.
- Privacy validation: writing P3 to a P0 card raises `PrivacyClassViolation`.

**Risks:** Data migration complexity. Mitigation: dual-write window with reconciliation; no destructive cutover until 14d clean.

---

### Phase 11 — Tests (Conformance Suite) (6 person-days)

**Goal:** Build conformance suite for 12 of 15 augmentation operations; build the canonical end-to-end acceptance test.

**FR-IM References:** FR-IM-15

**Tasks:**
- Implement conformance harness in `backend/tests/conformance/` that exercises 12 augmentation ops.
- Implement the canonical $4,200 music-vendor invoice acceptance test with 18 observable behaviors (per FR-IM-15.3).
- Add property-based tests for envelope schema (`hypothesis` library).
- Add latency budgets to integration tests.
- CI gates: privacy test must pass; conformance must be green.

**Files to Create:**
- `backend/tests/conformance/__init__.py`
- `backend/tests/conformance/test_augmentation_ops.py` (12 tests)
- `backend/tests/conformance/test_e2e_acceptance.py` (the $4,200 invoice scenario)
- `backend/tests/conformance/test_privacy_classes.py`
- `backend/tests/conformance/fixtures/sample_music_vendor_invoice.pdf`
- `backend/tests/conformance/fixtures/expected_18_behaviors.yaml`

**Files to Modify:**
- `pyproject.toml` — add `hypothesis>=6.115`

**Dependencies:** all prior phases

**Verification Criteria:**
- 12 augmentation op tests green.
- E2E acceptance test green; all 18 behaviors observed in the right order.
- Privacy class enforcement test: P3 detection in any signal aborts with audit log entry.

**Risks:** Test flakiness due to Redis timing. Mitigation: deterministic time + Redis testcontainers per test session.

---

### Phase 12 — v2 Receptor (DEFERRED)

**Goal:** Inbound signal handling for Stewardship amendments.

**FR-IM References:** FR-IM-13 (v2)

**Status:** Skeleton only in v1. Full implementation deferred until Stewardship amendment schema is finalized (Q-IM-4).

---

## 5. File-by-File Changes

### New files

| File | Purpose | Phase |
|------|---------|-------|
| `backend/membrane/__init__.py` | Package init | 1 |
| `backend/membrane/perturbations.py` | 10-signal registry | 1 |
| `backend/membrane/envelope.py` | ImpactSignal Pydantic | 1 |
| `backend/membrane/schemas/impact_signal_v1.json` | JSON Schema | 1 |
| `backend/membrane/feature_flags.py` | Per-FR-IM toggles | 1 |
| `backend/membrane/distiller/base.py` | Distiller base | 1 |
| `backend/membrane/distiller/accounting.py` | Concrete distillers | 7 |
| `backend/membrane/redactor/__init__.py` | Redactor entry | 7 |
| `backend/membrane/redactor/pseudonym_table.py` | Pseudonym mgmt | 7 |
| `backend/membrane/redactor/privacy_audit.py` | Privacy audit | 7 |
| `backend/membrane/emit.py` | Public emit() | 7 |
| `backend/membrane/transport/redis_client.py` | Redis client | 2 |
| `backend/membrane/transport/channels.py` | 13 channels | 2 |
| `backend/membrane/transport/publisher.py` | Publisher | 2 |
| `backend/membrane/transport/consumer.py` | Consumer | 2 |
| `backend/membrane/transport/dead_letter.py` | DLQ | 2 |
| `backend/membrane/guiders/base.py` | Guider base | 4 |
| `backend/membrane/guiders/accounting_integrity.py` | NEW guider | 4 |
| `backend/membrane/guiders/payment_dedup.py` | NEW guider | 4 |
| `backend/membrane/guiders/polity_and_deference.py` | reused | 4 |
| `backend/membrane/guiders/abundance_and_stewardship.py` | reused | 4 |
| `backend/membrane/guiders/witness_and_provenance.py` | reused | 4 |
| `backend/membrane/guiders/dignity.py` | reused | 4 |
| `backend/membrane/cascade.py` | Cascade runner | 4 |
| `backend/membrane/hitl/dispatcher.py` | HITL email | 6 |
| `backend/membrane/hitl/resume.py` | Resumption | 6 |
| `backend/membrane/hitl/templates/escalation_email.j2` | Email tpl | 6 |
| `backend/membrane/approval/router.py` | Authority routing | 8 |
| `backend/membrane/approval/dual_approval.py` | Dual approval | 8 |
| `backend/membrane/payments/dedup_table.py` | Dedup table | 9 |
| `backend/skills/registry.py` | Skill registry | 3 |
| `backend/skills/router.py` | Skill router | 3 |
| `backend/skills/orchestrator/invoice_processing_workflow/flow.py` | CrewAI Flow | 3 |
| `backend/skills/conversationalist/hitl_invoice_gate/{SKILL.md,entry.py}` | HITL skill | 6 |
| `backend/skills/worker/{credit_memo_handler,payment_matching,ach_file_generator,recurring_je_drafter}/{SKILL.md,entry.py}` | New worker skills | 3 |
| `backend/skills/researcher/denomination_rules/{episcopal,methodist,baptist}/SKILL.md` | Denom subskills | 3 |
| `backend/skills/reviewer/restriction_validator/{SKILL.md,entry.py}` | Restriction reviewer | 3 |
| `backend/skills/receptor/stewardship_amendment_receiver/SKILL.md` | v2 stub | 3 |
| `backend/cards/store.py` | CardStore | 10 |
| `backend/cards/ledger.py` | Decision Ledger | 10 |
| `backend/cards/episode.py` | Episode Memory | 10 |
| `backend/cards/reconcile.py` | Drift job | 10 |
| `backend/cards/dual_write.py` | Dual-write shim | 10 |
| `backend/cards/schemas/*.json` | 7 card schemas | 10 |
| `docker-compose.yml` (root) | Redis Stack | 2 |
| `backend/tests/test_phase1_envelope.py` ... `test_phase11_*` | Phase tests | per |
| `backend/tests/conformance/*` | Conformance suite | 11 |

### Modified files

| File | Reason | Phase |
|------|--------|-------|
| `pyproject.toml` | Add `redis`, `jsonschema`, `uuid7`, `hypothesis` | 1, 2, 11 |
| `backend/main.py` | Startup hooks, `/v2/` routes, Redis health | 2, 6, 8, 10 |
| `backend/flow.py` | Replace ad-hoc orchestration with `membrane.emit()` | 5, 7 |
| `backend/scheduler.py` | Emit `APPROVAL_DEADLINE_PRESSURE` | 5 |
| `backend/tools/pdf_extractor.py` | Emit `INVOICE_INGESTED` | 5 |
| `backend/tools/gl_mapper.py` | Emit `MAPPING_CONFIDENCE_LOW` | 5 |
| `backend/tools/budget_comparator.py` | Emit `BUDGET_OVERAGE_RISK` | 5 |
| `backend/tools/denomination_rules.py` | Emit `FUND_RESTRICTION_VIOLATION` | 5 |
| `backend/tools/journal_builder.py` | Emit `JOURNAL_ENTRY_READY` | 5 |
| `backend/tools/plaid_store.py` | Emit `RECONCILIATION_EXCEPTION` | 5 |
| `backend/tools/payment_recommender.py` | Emit `PAYMENT_DEDUP_RISK`; cascade pre-check | 5, 9 |
| `backend/tools/nacha_generator.py` | Refuse if cascade BLOCK | 9 |
| `backend/tools/check_generator.py` | Refuse if cascade BLOCK | 9 |
| `backend/tools/cc_generator.py` | Refuse if cascade BLOCK | 9 |
| `backend/tools/approval_audit.py` | Wrap Decision Ledger | 10 |
| `backend/tools/approval_chain_resolver.py` | Pure-fn output for cascade | 4, 8 |
| `backend/tools/budgetary_authority.py` | Structured authority records | 4, 8 |
| `backend/tools/je_state.py` | Dual-write to Memory Card | 10 |
| `backend/tools/risk_summary.py` | Dual-write to Risk Card | 10 |
| `backend/tools/skill_registry.py` | Bridge to new registry | 3 |
| `backend/integrations/acs_realm/acs_actions.py` | Cascade veto check | 8 |
| `backend/skills/orchestrator/invoice_processing_workflow/SKILL.md` | Fill in scaffolded SKILL.md | 3 |
| `backend/skills/worker/{pdf_extraction,line_item_classifier,gl_account_mapper,journal_entry_builder,expense_taxonomy_v1}/SKILL.md` | Fill in scaffolds | 3 |
| `backend/skills/researcher/{coa_reference_loader,vendor_history_lookup}/SKILL.md` | Fill in scaffolds | 3 |
| `backend/skills/reviewer/{allocation_reviewer,fraud_detector,risk_assessor}/SKILL.md` | Fill in scaffolds | 3 |
| `backend/skills/membrane/accounting_domain_distillation/SKILL.md` | Wire to distiller core | 3, 7 |

---

## 6. Risks & Open Items

### Blockers

- **Q-5 (HARD BLOCKER for Phase 8 production):** GL → budget-owner mapping seed data from Matt Babcock.
  - **Workaround:** ship Phase 8 with stub mapping in `backend/data/gl_owner_mapping.stub.json`; behind feature flag.

### Open items inherited

- Q-1 through Q-4, Q-6 through Q-12 from EIME spec (status: tracked in source spec; no immediate impact on this plan).

### New open items (Q-IM)

- **Q-IM-1:** Pseudonym table rotation policy (cadence + key-storage). Required before tenant-1 ships in Phase 7. Default: 90-day rotation, AWS KMS-stored keys.
- **Q-IM-2:** Episode Card 6-week finalization SLA confirmation (vs. 4 or 8 weeks). Affects Phase 10 retention.
- **Q-IM-3:** `trace_id` propagation across the Cowork (Stewardship) boundary. Plan: prefix with `embark.` and preserve through cross-domain emissions.
- **Q-IM-4:** Stewardship amendment schema (deferred to v2; Phase 12).

### Operational risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Redis outage halts publishing | Medium | High | Local outbox table with retry; degraded mode disables emission, logs warning |
| Schema drift between dev and prod | Low | High | CI validates JSON Schemas; deploys carry schema digest |
| Privacy class regression | Low | **Critical** | Mandatory unit tests; CI gate; alerting on dead-letter for `PrivacyClassViolation` |
| Bloom filter false positive (payment-dedup) | Medium | Medium | Bloom is Stage 1; exact lookup confirms before BLOCK |
| HITL token leakage | Low | High | Short TTL, single-use, signed, bound to flow_run_id |
| Card store / JSON drift | Medium | Medium | Nightly reconcile job; alert on drift > 0 |

---

## 7. Backward Compatibility Strategy

1. **HTTP API:** all existing endpoints remain operational. New Flow-based endpoints added under `/v2/`. No breaking changes to request/response shapes for at least 2 sprints after Phase 5.
2. **State files:** existing JSON files in `backend/data/` continue to be authoritative until Phase 10 completes its dual-write reconciliation window. Card Store is shadow during that window.
3. **Tool imports:** all `backend/tools/*.py` modules retain their public function signatures. SKILL.md packages wrap them; do not replace them.
4. **Feature flags:** every FR-IM has a flag in `backend/membrane/feature_flags.py`. A flag-off state restores pre-membrane behavior. Operators can disable any layer independently.
5. **Cutover:** JSON writers are deleted only after 14 consecutive days of zero drift. Deletion lands in a single PR titled `CUTOVER: cards-only state` so it is trivially revertable.
6. **Rollback:** revert the cutover PR, re-enable JSON writers, set Card Store to read-shadow. Data loss bounded to anything Card-only since cutover (recoverable from Card Store dump).

---

## 8. Testing Strategy

### Unit tests (every new component)

- Publisher: round-trip + retry + DLQ
- Consumer: idempotency, ack, replay
- Distiller: each per-perturbation distiller produces expected payload
- Redactor: P0/P1/P2 paths produce correct redacted shapes; P3 raises
- PseudonymTable: determinism within key, rotation correctness
- Each guider (6): at least 3 verdict types each
- Cascade: ordering preserved; first BLOCK terminates; ANNOTATEs accumulate
- CardStore: optimistic-lock CAS; privacy validation on write
- Decision Ledger: SHA-256 chain integrity; tamper detection
- Episode Memory: write/read; finalize lifecycle

### Integration tests

- Cascade traversal scenarios for each verdict type (BLOCK, ESCALATE, ANNOTATE, DEFER)
- Cross-domain publish (`JOURNAL_ENTRY_READY` → Stewardship channel, Pub/Sub `processing_status`)
- HITL: low-confidence → suspend → email → resume → posting
- Dual-approval: signal requires two approvers; one approval insufficient
- Payment dedup: Vanco then ACH within window blocks second attempt

### Conformance tests (FR-IM-15)

- 12 of 15 augmentation operations exercised; output matches expected envelopes
- Canonical $4,200 music-vendor invoice end-to-end → 18 observable behaviors, in order, with correct privacy classes and provenance chain

### Privacy enforcement tests

- P3 detection in any payload aborts publication and logs to privacy audit
- P2 fields aggregated correctly (cohort size ≥ k threshold)
- P1 vendor_id consistently pseudonymized within key epoch
- Pseudonym audit can decode P1 IDs for legitimate audit query

### Idempotency tests

- Same `signal_id` published twice → consumer processes once
- Hard-block (62, 68) retry semantics: same signal returns same blocked decision until underlying Card mutates

### Load / performance

- 100 invoices/min sustained for 10 min: no DLQ growth, p95 emit→consume < 500ms

---

## 9. Deployment Plan

### Dependencies (new in pyproject.toml)

```
redis>=5.2
jsonschema>=4.23
uuid7>=0.1
hypothesis>=6.115  # dev only
```

(`crewai>=0.86.0` already present and supports the Flow API at this version.)

### Environment variables (new)

| Var | Purpose | Example |
|-----|---------|---------|
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `MEMBRANE_ENV` | Environment label | `dev` / `sandbox` / `prod` |
| `SKILL_LIB_PATH` | Skills root | `backend/skills` |
| `CARD_STORE_DSN` | Card Store backend | `sqlite:///backend/data/cards.db` (dev) |
| `PSEUDONYM_KEY_ID` | Active pseudonym key | `PSK-2026-Q2` |
| `MEMBRANE_FEATURE_FLAGS` | JSON of FR-IM toggles | `{"FR-IM-04": true, ...}` |

### Deployment sequence

1. **Dev:** add Redis Stack via docker-compose; run migration runner that initializes the perturbation registry and creates Redis Streams + consumer groups. Smoke test with conformance suite.
2. **Sandbox tenant:** point `REDIS_URL` to managed Redis; run `backend/cards/migrate.py` to initialize Card Store; deploy with all FR-IM flags **off** initially. Smoke test. Flip flags on one at a time, verifying each phase's verification criteria.
3. **Production tenant:** repeat sandbox sequence; require 7-day clean run on sandbox before prod.

### Migration runner

- `backend/scripts/init_membrane.py` — creates Redis Streams, consumer groups, dead-letter queue, indexes; idempotent.
- `backend/scripts/seed_pseudonym_keys.py` — writes initial pseudonym key (rotation cadence per Q-IM-1).

### Rollback strategy

- Per-FR-IM feature flags allow instant disable.
- Card Store cutover PR is single-commit revertable.
- Redis can be flushed and pipelines re-run from JSON state if needed (lossless during dual-write window).

---

## 10. Glossary (24 terms)

| Term | Definition |
|------|------------|
| **Membrane** | Translation-and-governance boundary between a domain (Accounting) and the broader event mesh. |
| **Outer Membrane** | The outbound side: Distiller → Redactor → Cascade → Publisher pipeline. |
| **Distiller** | Strips internal reasoning and reduces internal state to a domain-public payload. |
| **Redactor** | Enforces privacy class hierarchy; pseudonymizes P1, drops P2, refuses P3. |
| **Publisher** | Emits the final ImpactSignal envelope to a Redis Stream or Pub/Sub channel. |
| **Cascade** | Six-position guider chain that evaluates a signal before publication. |
| **Guider** | One position in the cascade; returns PASS / ANNOTATE / BLOCK / ESCALATE / DEFER. |
| **Receptor** | The inbound side of the membrane (v2: Stewardship → Accounting). |
| **ImpactSignal** | Versioned envelope schema (v1) carrying perturbation payloads across the mesh. |
| **Perturbation** | Typed signal emitted at a pipeline point (10 in EIME: IDs 59–68). |
| **Privacy Class** | P0 (public-operational), P1 (pseudonymous-operational), P2 (pastoral-sensitive), P3 (highly protected, never crosses). |
| **Card** | Authoritative state record (9 types: Plan, Risk, Innovation, Episode, Context Pack, Memory, Decision Packet, Signal Memory, Practice). |
| **Decision Ledger** | Append-only log of Decision Packets; preserves SHA-256 hash chain. |
| **Decision Packet** | Card type recording an authoritative decision (cascade verdict + approver chain + outcome). |
| **Episode Card** | Card type representing a discrete processing run (one invoice → one Episode); finalized at 6 weeks. |
| **Context Pack** | Card type bundling references for a HITL session or escalation. |
| **Memory Card** | Card type for transient working memory; promoted to Episode on finalize. |
| **Signal Memory** | Card type recording emitted/received signals for replay. |
| **Risk Card** | Card type recording risk assessments. |
| **Plan Card** | Read-only card type EIME consumes (e.g., budget plan from Stewardship). |
| **Cowork** | The cross-domain collaboration plane between Embark domains. |
| **Flow** | A CrewAI Flow: long-running orchestration with suspend/resume. |
| **Authority Matrix** | The role × GL × dollar-threshold mapping that determines approver chain. |
| **Trace ID** | Correlation identifier propagated through the entire workflow + cards + ledger entries. |

---

## Appendix A: Sample ImpactSignal envelope (v1)

```json
{
  "schema_version": "1.0",
  "signal_id": "01HXP7K9D8Z9V2W3R4S5T6U7V8",
  "perturbation_id": 63,
  "perturbation_name": "JOURNAL_ENTRY_READY",
  "trace_id": "embark.tx.2026-05-07.0001",
  "emitted_at": "2026-05-07T14:33:21.103Z",
  "emitter": {
    "domain": "accounting",
    "skill": "journal_entry_builder",
    "version": "1.0.0"
  },
  "privacy_class": "P0",
  "crosses_membrane": true,
  "channel": "impact:proposed:journal_entry_ready",
  "payload": {
    "je_id": "JE-2026-001234",
    "amount_usd": 4200.00,
    "vendor_pseudonym": "vnd_8f3c1e",
    "gl_accounts": ["6100-Music-Programs"],
    "fund_codes": ["UNRESTRICTED"]
  },
  "provenance": {
    "derivation_pipeline": [
      "pdf_extraction:1.0.0",
      "line_item_classifier:1.0.0",
      "gl_account_mapper:1.0.0",
      "journal_entry_builder:1.0.0"
    ],
    "cascade_verdicts": [
      {"guider": "accounting-integrity", "verdict": "PASS"},
      {"guider": "payment-dedup", "verdict": "PASS"},
      {"guider": "polity-and-deference", "verdict": "ANNOTATE", "note": "dual_approval_required"},
      {"guider": "abundance-and-stewardship", "verdict": "PASS"},
      {"guider": "witness-and-provenance", "verdict": "PASS"},
      {"guider": "dignity", "verdict": "PASS"}
    ]
  },
  "retention_days": 365
}
```

---

## Appendix B: Phase-to-FR-IM coverage matrix

| Phase | FR-IM-01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 |
|-------|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 |  | ● | ● | ◔ |  |  |  |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  | ● |  |  |  |  |  |  |  |  |  |
| 3 | ● |  |  |  |  |  |  |  |  |  |  |  | ◔ |  |  |
| 4 |  |  |  |  | ● |  |  |  |  |  |  |  |  |  |  |
| 5 |  | ● |  |  |  |  |  |  |  |  |  |  |  |  | ◔ |
| 6 |  |  |  |  |  |  |  |  |  | ● |  |  |  | ◔ |  |
| 7 |  |  |  | ● | ● |  |  | ● |  |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |  |  | ● |  |  |  |  |  |  |
| 9 |  | ◔ |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 10 |  |  |  |  |  |  | ● |  |  |  | ● | ● |  |  |  |
| 11 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | ● |
| 12 |  |  |  |  |  |  |  |  |  |  |  |  | ● |  |  |

Legend: ● full, ◔ partial.

---

**End of Plan.**
