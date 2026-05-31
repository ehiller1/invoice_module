# NBA Domain Skill — nba-eime (Embark Invoice Mapping Engine)

Configuration read at runtime by the EIME NBA crew. Treat as code.

## 1. Goal statement
Keep the parish's books accurate, compliant, and on-time with the least human
toil — every invoice mapped correctly, every JE posted within SLA, no fund
restriction or duplicate payment ever slipping through, and human attention
spent only where judgment is genuinely required.

## 2. Trigger contexts
| perturbation_id | debounce | cooldown | notes |
|---|---|---|---|
| eime.journal_entry_ready | 30s | 5m per JE | candidate posting / routing decision |
| eime.budget_overage_risk | 60s | 30m per fund | reallocation / flag decision |
| eime.reconciliation_exception | 60s | 15m per item | resolution-path decision |
| eime.approval_deadline_pressure | 0s | 10m per approval | escalation timing decision |
| eime.mapping_confidence_low | 60s | 20m per invoice | reclassification suggestion |

Hard blocks (eime.fund_restriction_violation, eime.payment_dedup_risk) are NOT
trigger contexts — they are non-overridable and never enter NBA arbitration.

## 3. Candidate action library
- action_type: post_je_now
  required_fields: [je_id]
  eligibility_predicates: [no_active_hard_block, within_amount_tolerance, recurring_template_match]
  reversibility: partially_reversible
  actor_class: agent_eligible
- action_type: route_to_approval
  required_fields: [je_id, target_stage]
  eligibility_predicates: [no_active_hard_block]
  reversibility: reversible
  actor_class: either
- action_type: defer_posting
  required_fields: [je_id, defer_reason]
  eligibility_predicates: []
  reversibility: reversible
  actor_class: either
- action_type: request_human_review
  required_fields: [item_id, review_reason]
  eligibility_predicates: []
  reversibility: reversible
  actor_class: agent_eligible
- action_type: propose_reclassification
  required_fields: [invoice_id, suggested_gl_account]
  eligibility_predicates: [confidence_below_floor]
  reversibility: reversible
  actor_class: either
- action_type: batch_approve_high_confidence
  required_fields: [classification_ids]
  eligibility_predicates: [all_above_confidence_floor, actor_is_budget_owner_plus]
  reversibility: partially_reversible
  actor_class: human_only
- action_type: escalate_sla
  required_fields: [approval_id, next_tier]
  eligibility_predicates: [nearing_sla_deadline]
  reversibility: reversible
  actor_class: agent_eligible
- action_type: propose_dedup_resolution
  required_fields: [exception_id, candidate_match]
  eligibility_predicates: []
  reversibility: reversible
  actor_class: either
- action_type: recommend_budget_reallocation
  required_fields: [fund_id, amount]
  eligibility_predicates: [breaches_budget_threshold]
  reversibility: reversible
  actor_class: human_only

## 4. Impact dimensions
1. posting_accuracy_delta — expected change in classification/posting correctness
2. sla_risk_delta — change in probability of breaching an approval/close deadline
3. compliance_exposure — change in fund-restriction / policy risk (harm axis)
4. human_toil_delta — minutes of human review created or saved (harm axis when positive)
5. cash_timing_impact — effect on payable timing / cash position

## 5. Scoring weights
- propensity: 0.25 — likelihood the action achieves its intended posting/approval outcome
- context: 0.20 — fit with current fiscal period, role authority, and church state
- value: 0.30 — accuracy + toil savings + on-time close (the parish's stated priority)
- levers: 0.25 — controllability/reversibility; irreversible actions are penalized
Sum = 1.0. Do-nothing baseline: the cost of leaving the JE unposted / the
exception open until the next human pass; every candidate must beat it.

## 6. Simulation depth
Default 2 hops. No twin_simulator registered. Posting outcomes are observable
within one reconciliation cycle, so depth-2 with uncertainty bands is sufficient;
deeper lookahead would compound estimation error on vendor/cash behavior.

## 7. Escalation thresholds
Escalate to a human UCS card (cabinet surface) when ANY of:
- top candidate is irreversible or actor_class=human_only
- compliance_exposure projection is non-zero
- the action is post_je and the consuming actor is below TREASURER_ADMIN
- top-1 vs top-2 arbitration spread < 0.10 (genuine ambiguity)
- trigger context lacks sufficient state to project (Recommender defers)

## 8. Surface bindings
- post_je_now / batch_approve_high_confidence -> Delegate (treasurer_dashboard)
- recommend_budget_reallocation / propose_reclassification -> Analyze (cabinet)
- escalate_sla / request_human_review -> Automate (approvals_hitl)
- propose_dedup_resolution -> Analyze (reconciliation)
