# NBA Domain Skill — Archetype Template

Copy this file to `nba-<domain>.md` to add a new NBA action context. The crew
reads the active file at runtime; treat it as configuration, not documentation.
All eight sections are required.

## 1. Goal statement
The target state this NBA layer steers toward. One or two sentences.

## 2. Trigger contexts
Which incoming perturbation types warrant NBA evaluation, with debounce/cooldown.
| perturbation_id | debounce | cooldown | notes |

## 3. Candidate action library
5–12 typed action shapes the Candidate Generator may propose.
- action_type: snake_case id
  required_fields: [...]
  eligibility_predicates: [...]
  reversibility: reversible | partially_reversible | irreversible
  actor_class: human_only | agent_eligible | either

## 4. Impact dimensions
3–6 dimensions the Simulator projects along; at least one must be a harm axis.

## 5. Scoring weights
Four Pega factors summing to 1.0 (propensity, context, value, levers) + a
do-nothing baseline anchor, each with a one-line justification.

## 6. Simulation depth
Default 2. Document explicitly any reason to go deeper (requires a registered
twin_simulator tool).

## 7. Escalation thresholds
When the Recommender escalates to a human UCS card instead of autonomous publish.

## 8. Surface bindings
Default UCS mode (Analyze / Delegate / Automate / Shadow) per recommendation type.
