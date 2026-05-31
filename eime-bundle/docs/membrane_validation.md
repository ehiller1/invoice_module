# EIME — Membrane Validation

**Bundle:** eime-bundle
**Module id:** eime
**Tier:** parish
**Validated against:** `~/laptop_embeddings/guiders_perturbations/membranes.yaml`
**Method:** `registry_client.py show --membrane <id>` for each referenced id.

> Membrane references are *validated, not invented*. Every id below was
> resolved against the canonical manifest. No id is proposed-new.

## Referenced membranes

| Membrane id | Tier | Pattern | Status | Used by |
|---|---|---|---|---|
| `mem.ein.parish.outer` | parish | `mem.<domain>.outer` | ✓ RESOLVED | outer cascade (all UCs) |
| `mem.ein.parish.intent_gate` | parish | `mem.<domain>.intent_gate` | ✓ RESOLVED | UC-7 intent routing |
| `mem.ein.parish.nba` | parish | `mem.<domain>.nba` | ✓ RESOLVED | UC-6 next-best-action |
| `mem.ein.parish.cabinet_gate` | parish | `mem.<domain>.cabinet_gate` | ✓ RESOLVED | UC-8 cabinet/management views |
| `mem.ein.parish.ledger_export` | parish | `mem.<domain>.ledger_export` | ✓ RESOLVED | decision-ledger federation export |

## Result

- **5 / 5 resolved** against the canonical parish membrane set.
- **0 reframed**, **0 proposed-new**.
- The parish tier is confirmed (sibling to steward-bundle in the same EIN domain).
- No membrane decision is required at Checkpoint 2 — the set is canonical as-is.
