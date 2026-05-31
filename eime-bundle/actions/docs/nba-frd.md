# EIME Next Best Action (NBA) Layer — Functional Requirements

> Long-form FRD source. Convert to `nba-frd.docx` via the `docx` skill before
> hand-off (tracked as an open item in manifest.yaml).

## 1. Executive summary
The EIME NBA layer watches the parish accounting event mesh and, for events
that warrant it, recommends the single best next action — post, route, defer,
reclassify, escalate, or do nothing — with a projected impact preview. It never
executes; it recommends. Hard blocks (restricted-fund violations, duplicate
payments) are never arbitrated. The goal is accurate, compliant, on-time books
with the least human toil.

## 2. Architecture overview
Six fixed CrewAI archetypes orchestrated as an event-driven Flow:
Sensor → CandidateGenerator → Simulator → Arbiter → Recommender → (router) →
agent-consumer or human UCS card; a parallel OutcomeListener closes the loop.
Domain behavior is configuration in `skills/nba/nba-eime.md`, read at runtime.

## 3. Pega four-factor model (EIME calibration)
propensity 0.25 · context 0.20 · value 0.30 · levers 0.25. Value is weighted
highest because the parish's stated priority is accurate, on-time close with
toil savings. Every candidate must beat a do-nothing baseline.

## 4. Bounded lookahead
Simulation depth = 2 hops with uncertainty bands; no twin simulator registered.
Posting outcomes are observable within one reconciliation cycle, so depth-2 is
sufficient and avoids compounding estimation error.

## 5. ReflAct goal-state reflection
The Recommender states the goal, the current distance from goal, then justifies
the chosen action — not the other way around.

## 6. Domain skill walkthrough
See `skills/nba/nba-eime.md`: goal, trigger contexts, 9-action library, 5 impact
dimensions (two harm axes), scoring weights, escalation thresholds, surface
bindings. New action contexts are added by authoring a new `nba-<domain>.md`.

## 7. Mesh integration
Subscribes: eime.journal_entry_ready, eime.budget_overage_risk,
eime.reconciliation_exception, eime.approval_deadline_pressure,
eime.mapping_confidence_low. Publishes: embark.surface.eime.recommendation.v1.
Always writes a Decision Ledger entry. See `perturbations/subscriptions.yaml`.

## 8. UCS surface bindings
post_je_now/batch_approve → Delegate (treasurer_dashboard);
recommend_budget_reallocation/propose_reclassification → Analyze (cabinet);
escalate_sla/request_human_review → Automate (approvals_hitl);
propose_dedup_resolution → Analyze (reconciliation).

## 9. Open dependencies
- `nba-frd.docx` not yet rendered (this markdown is the source).
- `twin_simulator` tool intentionally unimplemented (depth-2 default).
- All subscribed perturbations exist in the substrate; no missing inputs.

## 10. Acceptance tests
Mapped to `tests/fixtures/fixtures.json`: happy-path post, cooldown
suppression, conflicting projections, irreversible-candidate escalation,
insufficient-context defer.
