# EIME — Source Extraction

**Bundle:** eime-bundle
**Module id:** eime
**Domain:** ein.parish.financial_intelligence
**Input shape:** A (existing implementation: `backend/` code + `docs/`)
**Tier:** parish (sibling to steward-bundle in the same EIN domain)

> Brownfield extraction. Every item below traces to code in `backend/`. Source
> of record is the implementation, not a written FRD.

## Use cases

### UC-1 — Invoice ingestion and GL mapping
- **Actors:** FINANCE_STAFF, Invoice Document Extractor, COA Loader, Expense Classifier, GL Account Mapper.
- **Trigger:** an invoice PDF enters the pipeline (`INVOICE_INGESTED`).
- **Inputs:** invoice document, church chart of accounts, vendor history.
- **Decision points:** which expense taxonomy applies; which GL account each line maps to; confidence of the mapping.
- **Success criteria:** every line item mapped to a GL account with a confidence score; low-confidence mappings flagged (`MAPPING_CONFIDENCE_LOW`).
- Code: `backend/agents/invoice_crew.py` (7-agent sequential crew), `backend/skills/worker/*`.

### UC-2 — Journal entry drafting and fund-accounting compliance
- **Actors:** Journal Entry Drafter/Builder, Compliance Officer & Policy Enforcer.
- **Trigger:** a mapped invoice or a natural-language JE request.
- **Inputs:** mapped lines, fund restrictions, budget thresholds, policy set.
- **Decision points:** is the posting within budget; does it violate a restricted-fund rule; does any policy gate fire.
- **Success criteria:** balanced JE assembled (`JOURNAL_ENTRY_READY`); hard blocks raised for `FUND_RESTRICTION_VIOLATION`; `BUDGET_OVERAGE_RISK` / `POLICY_VIOLATION` surfaced.
- Code: `backend/agents/agents.py` (drafting, compliance), `backend/db/fund_restriction_store.py`, `backend/db/policy_store.py`.

### UC-3 — Human-in-the-loop approval
- **Actors:** BUDGET_OWNER, TREASURER, HITL Gate Coordinator.
- **Trigger:** a JE ready for review, or an escalation (`HITL_ESCALATION`).
- **Inputs:** drafted JE, approval chain, role of the acting user.
- **Decision points:** approve / reject at each tier of the approval chain; escalate on SLA pressure (`APPROVAL_DEADLINE_PRESSURE`).
- **Success criteria:** multi-tier approval recorded in the decision ledger; deadlines tracked by the scheduler.
- Code: `backend/routes/approvals.py`, `backend/routes/hitl.py`, `backend/scheduler.py`, `backend/decision_ledger.py`.

### UC-4 — Bank reconciliation
- **Actors:** Bank Reconciliation Specialist, Plaid integration.
- **Trigger:** bank feed sync or recon run.
- **Inputs:** Plaid transactions, journal entries, structural matcher rules.
- **Decision points:** match vs. exception; dedup of candidate payments (`PAYMENT_DEDUP_RISK`).
- **Success criteria:** transactions matched; unresolved items raised as `RECONCILIATION_EXCEPTION`.
- Code: `backend/routes/reconciliation.py`, `backend/db/recon_store.py`, `backend/integrations/plaid_client.py`, `backend/membrane/reconciliation/*`.

### UC-5 — Autonomous posting of recurring entries
- **Actors:** Autonomous Posting Engine.
- **Trigger:** scheduled recurring JE due.
- **Inputs:** recurring JE templates, learned tolerances.
- **Decision points:** post automatically vs. defer for review based on tolerance/learning.
- **Success criteria:** eligible entries posted; others deferred; learning updated.
- Code: `backend/db/recurring_learning_store.py`, `backend/agents/agents.py` (auto_post).

### UC-6 — Advisory analysis and next-best-action
- **Actors:** Accounting Advisor & Auditor, NBA crew.
- **Trigger:** advisory request, or a perturbation that warrants a recommendation.
- **Inputs:** decision patterns, variance, vendor analysis, policy history.
- **Decision points:** which recommendation to surface; scenario simulation of an action's impact.
- **Success criteria:** recommendation card emitted with evidence; scenario preview available.
- Code: `backend/membrane/nba/{crew,recommendation_card}.py`, `backend/membrane/scenario/{simulator,scenario_card}.py`, `backend/routes/recommendations.py`.

### UC-7 — Conversational query / intent routing
- **Actors:** parish user (treasurer/admin), HITL Gate Coordinator / conversationalist, agent Q&A interface.
- **Trigger:** a user asks a question or expresses an action conversationally.
- **Inputs:** the utterance, user role/authority, prior decisions.
- **Decision points:** classify intent; dispatch to the right agent/skill; answer questions or open a question card.
- **Success criteria:** intent classified and routed; answer or escalation produced.
- Code: `backend/tools/chat_router.py`, `backend/skills/router.py`, `backend/skills/dispatchers/*`, `backend/routes/questions.py`.

### UC-8 — Financial position and cabinet views
- **Actors:** treasurer, finance committee.
- **Trigger:** dashboard / cabinet request.
- **Inputs:** funds, budgets, YTD actuals, projections.
- **Success criteria:** financial position and per-principal cabinet items rendered.
- Code: `backend/routes/financial_position.py`, `backend/routes/cabinets.py`.

## Actors

| Actor | Description | Use cases |
|---|---|---|
| FINANCE_STAFF | Day-to-day staff entering/reviewing invoices | UC-1, UC-2 |
| BUDGET_OWNER | Approves spend against their budget | UC-3 |
| TREASURER / TREASURER_ADMIN | Final approval authority; admin overrides | UC-3, UC-5, UC-8 |
| Finance committee | Reviews position and policy | UC-6, UC-8 |
| Invoice crew (7 agents) | extractor, coa_loader, classifier, mapper, risk_officer, reviewer, builder | UC-1, UC-2 |
| Standalone agents (5) | drafting, reconciliation, compliance, auto_post, advisor | UC-2, UC-4, UC-5, UC-6 |
| Membrane archetypes (6) | orchestrator, researcher, worker, reviewer, conversationalist, membrane | all |
| Plaid | Banking data integration | UC-4 |
| ACS Realm | Church management system integration | UC-1, UC-8 |
| Email | Notifications | UC-3 |

## Events

10 module perturbations, defined in `backend/membrane/perturbations.py` (`_REGISTRY_SPEC`, ids 59–68):

| Name | Privacy | Crosses membrane | Retention | Fires when |
|---|---|---|---|---|
| INVOICE_INGESTED | P1 | no | 30d | new invoice enters pipeline |
| MAPPING_CONFIDENCE_LOW | P1 | no | 30d | mapper produces low-confidence GL suggestion |
| BUDGET_OVERAGE_RISK | P1 | no | 90d | posting would breach budget threshold |
| FUND_RESTRICTION_VIOLATION | P1 | no | 365d | HARD BLOCK: posting violates fund restriction |
| JOURNAL_ENTRY_READY | P0 | no | 365d | JE assembled; amounts FINANCE_STAFF+ only |
| PAYMENT_DEDUP_RISK | P1 | no | 180d | HARD BLOCK: candidate payment is a possible duplicate |
| RECONCILIATION_EXCEPTION | P1 | yes | 180d | recon produced unresolved exception |
| APPROVAL_DEADLINE_PRESSURE | P1 | yes | 30d | pending approval nearing SLA deadline |
| HITL_ESCALATION | P1 | yes | 180d | HITL review requested/escalated |
| POLICY_VIOLATION | P1 | yes | 365d | policy gate fired against a proposed action |

## Decisions

- **GL mapping** — mapper agent; inputs COA + classified line; outcomes: mapped account + confidence.
- **Compliance gate** — compliance agent; inputs fund restrictions, budget, policy; outcomes: allow / hard-block / flag.
- **Approval** — HITL chain; inputs role + chain config; outcomes: approve / reject / escalate per tier.
- **Reconciliation match** — recon specialist; inputs Plaid txns + JEs; outcomes: match / exception / dedup-block.
- **Auto-post eligibility** — auto_post engine; inputs tolerance/learning; outcomes: post / defer.
- **Intent dispatch** — chat router; inputs utterance + authority; outcomes: route to agent/skill, answer, or question card.

## Data flows

- invoice PDF → extractor → mapped lines → drafting → `JOURNAL_ENTRY_READY` → HITL → decision ledger
- Plaid → recon specialist → match/exception → `RECONCILIATION_EXCEPTION` → HITL
- compliance → policy/fund gates → `FUND_RESTRICTION_VIOLATION` / `BUDGET_OVERAGE_RISK` / `POLICY_VIOLATION`
- advisor / nba crew → recommendation card → recommendations surface
- scheduler → `APPROVAL_DEADLINE_PRESSURE` → HITL
- user utterance → chat_router → dispatcher → agent/skill → answer / question card

## KPIs and success measures

- Mapping confidence rate; share of invoices requiring HITL.
- Approval SLA adherence (driven by `APPROVAL_DEADLINE_PRESSURE`).
- Reconciliation match rate; open exception count.
- Fund-restriction and policy violation block counts.
- Autonomous posting rate vs. deferral.

## Constraints

- **Fund accounting integrity** — restricted funds must never be violated (hard block).
- **Payment dedup** — duplicate payments must be hard-blocked.
- **Role-based disclosure** — JE amounts visible to FINANCE_STAFF+ only (P0 perturbation).
- **Decision ledger** — every dispatch and outbound emission is recorded.
- **Shared Postgres** — all tables carry the `eime_` prefix (done in Phase 2/DBP) to avoid collision with sibling modules (`aco_*`, `intel_*`).

## Membranes referenced

eime is a **parish-tier** module. It maps onto the canonical EIN parish membrane set (validated in `membrane_validation.md`):

- `mem.ein.parish.outer` — outer cascade for the parish tier
- `mem.ein.parish.intent_gate` — intent routing gate
- `mem.ein.parish.nba` — next-best-action membrane
- `mem.ein.parish.cabinet_gate` — cabinet/management gate
- `mem.ein.parish.ledger_export` — decision-ledger export (federation)

## Conditional layer flags

| Flag | Value | Reason |
|---|---|---|
| knowledge_needs | **true** | `backend/tools/knowledge_base.py`, COA reference loader, vendor history lookup, embeddings/vector retrieval. |
| nba_needs | **true** | `backend/membrane/nba/{crew,recommendation_card}.py` + `scenario/simulator.py` (impact preview). |
| intent_routing_needs | **true** | `backend/tools/chat_router.py`, `skills/router.py`, conversationalist dispatcher. |
| context_needs | **true** | `decision_ledger.py`, `auth.py` role/authority gates, policy enforcement at dispatch. (Also auto-surfaced by intent_routing on an Embark/iQueue module.) |
| memory_stack_shim_needed | **false** | EIN Memory Fabric presumed provisioned for the parish tier (sibling to steward-bundle). |

## Extraction ambiguities

1. **Local perturbation ids (59–68) vs. canonical store.** The module defines its own integer ids; the canonical registry uses uuid/string ids. These 10 must be similarity-matched at the substrate layer (reuse vs. propose_new), not assumed new. This is the REG "orphan id" item from the readiness report.
2. **Guiders exist as Python only.** `backend/membrane/guiders/` has 6 guiders (accounting_integrity, dignity, polity_and_deference, abundance_and_stewardship, witness_and_provenance, payment_dedup) with no `guiders.yaml` / SKILL.md packaging. Capabilities and messages are designed at the substrate layer.
3. **Two agent layers + a crew.** invoice_crew (7 sequential), 6 membrane archetypes, and 5 standalone domain agents. The crew layer must reconcile these into one canonical `agents.yaml` + `crew.py`.
4. **EXT integration boundary.** ACS Realm uses Playwright inside the request path; flagged for the transport/packaging open_items, not redesigned here.
