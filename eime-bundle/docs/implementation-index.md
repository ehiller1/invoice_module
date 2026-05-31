# EIME Bundle — Implementation Index

> Developer hand-off index for the EIME (Embark Invoice Mapping Engine) parish-tier
> bundle. Start at `manifest.yaml`; this file maps each layer to its integration points.

## 1. What this bundle is
A parish-tier invoice-to-GL agent for EmbarkNow, sibling to Steward in the
`ein.parish.financial_intelligence` domain. 60 design files across 7 layers,
plus 43 staged registry deltas awaiting Checkpoint 3 approval.

## 2. Layer map

| Layer | Directory | Integrates with |
|-------|-----------|-----------------|
| Substrate | `membranes/`, `perturbations/`, `guiders/`, `agents/eime/pack_registration.yaml` | Canonical registry + membranes.yaml |
| Crew | `agents/`, `tasks/`, `crews/`, `skills/`, `prompts/`, `tools/` | CrewAI runtime |
| Context | `context/` | Memory fabric + decision matrix evaluator |
| Knowledge | `knowledge/` | COA / fund-restriction knowledge sources |
| Surface | `events/`, `interactions/` | Intent router + agent-output-display |
| Actions (NBA) | `actions/` | Mesh subscribe → recommendation publish |
| Transport | `mesh/` | Parish-tier Redis (streams + pub/sub) |

## 3. Key integration seams
- **Intent routing** — authoritative source `events/intent_registry.yaml`;
  flow in `events/capture_flow.yaml`; verdict/authority gating via
  `events/resolution_contract.yaml` → `context/decision_matrix.yaml`.
- **Authority model** — 3 EIME roles (FINANCE_STAFF=1, BUDGET_OWNER=2,
  TREASURER_ADMIN=3). Posting requires TREASURER_ADMIN; P0 amount disclosure
  requires FINANCE_STAFF; see `events/decision_policy.yaml`.
- **Hard blocks** — restricted-fund violations and duplicate payments are
  mechanical, non-overridable, excluded from NBA arbitration; retained forever
  on `ein.parish.eime.hard_blocks`.
- **Surface emission** — all 5 surfaces use the `declarative` tier; templates in
  `interactions/emission_templates/`; CloudEvents follow
  `embark.surface.eime.<action>.v1`.
- **Mesh** — 11 streams + 2 pub/sub channels in `mesh/mesh_config.yaml`; envelope
  is CloudEvents-shaped (`mesh/event_envelope.schema.json`).

## 4. Open items
See `manifest.yaml` `open_items:`. Blocking item: 43 staged registry entries
need Checkpoint 3 approval before `registry_client.py commit`.

## 5. Build order
Follow `manifest.yaml` `recommended_build_order:` (substrate → crew → context →
surface → actions → transport → packaging+commit).
