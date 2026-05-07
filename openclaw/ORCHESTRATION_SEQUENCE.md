# EIME Personal Cabinets — Delegation Orchestration Sequence

**Document:** Phase 3 Implementation Plan → Downstream Skill Invocations  
**Target:** Crewai-skills-architect, membrane-agent-designer, redis-mesh-wiring  
**Status:** Ready for Invocation  
**Generated:** 2026-05-07  

---

## Executive Summary

The delegation manifest specifies 6 delegations to be invoked to produce cabinet member skills and coordination infrastructure. The delegations are largely **independent** and can be **parallelized**. The recommended sequence is:

**Phase A (Parallel):** Invoke 5 skill-generation delegations simultaneously
- treasurer-queue-guardian-skills
- treasurer-decision-deputy-skills
- budget-owner-steward-skills
- finance-staff-intake-specialist-skills
- treasurer-cabinet-coordination-membrane

**Phase B (Sequential, after Phase A):** Invoke optional cross-cabinet mesh wiring
- cross-cabinet-event-mesh-wiring (optional for v1; defer to v2 if tight timeline)

**Total Duration:** ~1 hour for Phase A (parallelized), ~15 min for Phase B (sequential)

---

## Delegation Execution Plan

### Phase A — Skill Generation & Membrane Design (Parallelizable)

All 5 delegations in this phase are **independent** and have **no cross-dependencies**. They should be invoked simultaneously to save time.

#### Delegation 1: treasurer-queue-guardian-skills
**Target Skill:** crewai-skills-architect  
**Output:** 5 SKILL.md files for Queue Guardian  
**Produces:**
- `queue_monitoring` — Real-time queue status and stall detection
- `budget_threshold_scanner` — Budget threshold alerts and year-forward projections
- `vendor_risk_assessment` — Vendor history analysis and risk scoring
- `daily_queue_digest_generator` — Morning briefing composition
- `weekly_vendor_risk_reporter` — Vendor pattern trends and policy implications

**Output Path:** `~/.openclaw/workspace/treasurer/queue-guardian/skills/`

**Installation:**
```bash
# After crewai-skills-architect produces SKILL.md files:
cp <output>/queue_monitoring/SKILL.md ~/.openclaw/workspace/treasurer/queue-guardian/skills/
cp <output>/budget_threshold_scanner/SKILL.md ~/.openclaw/workspace/treasurer/queue-guardian/skills/
cp <output>/vendor_risk_assessment/SKILL.md ~/.openclaw/workspace/treasurer/queue-guardian/skills/
cp <output>/daily_queue_digest_generator/SKILL.md ~/.openclaw/workspace/treasurer/queue-guardian/skills/
cp <output>/weekly_vendor_risk_reporter/SKILL.md ~/.openclaw/workspace/treasurer/queue-guardian/skills/
```

**Verification:**
```bash
ls ~/.openclaw/workspace/treasurer/queue-guardian/skills/ | wc -l
# Expected: 5 SKILL.md files
```

---

#### Delegation 2: treasurer-decision-deputy-skills
**Target Skill:** crewai-skills-architect  
**Output:** 4 SKILL.md files for Decision Deputy  
**Produces:**
- `approval_decision_drafting` — Draft approval decisions in Treasurer's voice
- `fund_split_calculator` — Calculate optimal fund allocations
- `abundance_option_generator` — Generate reallocate/amend/phase alternatives
- `written_explanation_composer` — Compose canonical-cited explanations

**Output Path:** `~/.openclaw/workspace/treasurer/decision-deputy/skills/`

**Installation:**
```bash
cp <output>/approval_decision_drafting/SKILL.md ~/.openclaw/workspace/treasurer/decision-deputy/skills/
cp <output>/fund_split_calculator/SKILL.md ~/.openclaw/workspace/treasurer/decision-deputy/skills/
cp <output>/abundance_option_generator/SKILL.md ~/.openclaw/workspace/treasurer/decision-deputy/skills/
cp <output>/written_explanation_composer/SKILL.md ~/.openclaw/workspace/treasurer/decision-deputy/skills/
```

**Verification:**
```bash
ls ~/.openclaw/workspace/treasurer/decision-deputy/skills/ | wc -l
# Expected: 4 SKILL.md files
```

---

#### Delegation 3: budget-owner-steward-skills
**Target Skill:** crewai-skills-architect  
**Output:** 4 SKILL.md files for Budget Steward  
**Produces:**
- `gl_budget_monitor` — Track YTD spend and budget thresholds
- `year_forward_projection` — Estimate year-end position with seasonal adjustments
- `reallocation_proposal_generator` — Draft reallocation requests
- `weekly_budget_digest_generator` — Compose weekly briefings with insights

**Output Path:** `~/.openclaw/workspace/budget-owner/budget-steward/skills/`

**Installation:**
```bash
cp <output>/gl_budget_monitor/SKILL.md ~/.openclaw/workspace/budget-owner/budget-steward/skills/
cp <output>/year_forward_projection/SKILL.md ~/.openclaw/workspace/budget-owner/budget-steward/skills/
cp <output>/reallocation_proposal_generator/SKILL.md ~/.openclaw/workspace/budget-owner/budget-steward/skills/
cp <output>/weekly_budget_digest_generator/SKILL.md ~/.openclaw/workspace/budget-owner/budget-steward/skills/
```

**Verification:**
```bash
ls ~/.openclaw/workspace/budget-owner/budget-steward/skills/ | wc -l
# Expected: 4 SKILL.md files
```

---

#### Delegation 4: finance-staff-intake-specialist-skills
**Target Skill:** crewai-skills-architect  
**Output:** 5 SKILL.md files for Intake Specialist  
**Produces:**
- `document_intake_screening` — Validate extraction completeness and quality
- `vendor_lookup_and_flagging` — Check vendor registry and escalation history
- `gl_account_suggestion` — Suggest GL accounts with confidence bands
- `field_validator` — Validate field presence and format
- `anomaly_detector` — Detect unusual amounts, duplicates, quality issues

**Output Path:** `~/.openclaw/workspace/finance-staff/intake-specialist/skills/`

**Installation:**
```bash
cp <output>/document_intake_screening/SKILL.md ~/.openclaw/workspace/finance-staff/intake-specialist/skills/
cp <output>/vendor_lookup_and_flagging/SKILL.md ~/.openclaw/workspace/finance-staff/intake-specialist/skills/
cp <output>/gl_account_suggestion/SKILL.md ~/.openclaw/workspace/finance-staff/intake-specialist/skills/
cp <output>/field_validator/SKILL.md ~/.openclaw/workspace/finance-staff/intake-specialist/skills/
cp <output>/anomaly_detector/SKILL.md ~/.openclaw/workspace/finance-staff/intake-specialist/skills/
```

**Verification:**
```bash
ls ~/.openclaw/workspace/finance-staff/intake-specialist/skills/ | wc -l
# Expected: 5 SKILL.md files
```

---

#### Delegation 5: treasurer-cabinet-coordination-membrane
**Target Skill:** membrane-agent-designer  
**Output:** Coordination membrane config for Queue Guardian ↔ Decision Deputy  
**Produces:**
- `queue-guardian-decision-deputy.yaml` — Coordination membrane definition

**Output Path:** `~/.openclaw/workspace/treasurer/membranes/`

**Membrane Configuration:**
```yaml
# Example output structure
perturbation_type: "queue_guardian_escalation_alert"
initiator: "queue-guardian"
responder: "decision-deputy"
handoff_context:
  - item_id
  - escalation_reason
  - budget_context
  - vendor_history_snippet
  - recommended_routing_target
coordination_mechanism: "sessions_send"  # Lightweight OpenClaw coordination
timeout_seconds: 3600  # 1 hour for decision draft
```

**Installation:**
```bash
cp <output>/queue-guardian-decision-deputy.yaml ~/.openclaw/workspace/treasurer/membranes/
```

**Verification:**
```bash
test -f ~/.openclaw/workspace/treasurer/membranes/queue-guardian-decision-deputy.yaml && echo "✓ Membrane installed"
```

---

### Phase B — Optional Cross-Cabinet Event Mesh (Sequential, Defer to v2)

This delegation is **optional for v1** and should be **deferred to v2** unless cross-cabinet coordination is critical for initial deployment. The basic cabinet functionality works without full event mesh integration (using webhooks + lightweight OpenClaw coordination instead).

#### Delegation 6: cross-cabinet-event-mesh-wiring
**Target Skill:** redis-mesh-wiring  
**Output:** Redis channel configuration for cabinets  
**Produces:**
- `mesh_config.yaml` — Channel routing and consumer groups
- `asyncapi.yaml` — Event schema definitions and contract

**Output Path:** `~/.openclaw/workspace/mesh-wiring/`

**Channels to Wire:**
```yaml
channels:
  - embarknow:accounting:impact:proposed:invoice_ingested
  - embarknow:accounting:impact:proposed:hitl_escalation
  - embarknow:accounting:impact:proposed:hitl_decision_returned
  - embarknow:accounting:impact:proposed:approval_deadline_pressure
  - embarknow:accounting:impact:proposed:budget_overage_risk
  - embarknow:accounting:impact:proposed:journal_entry_ready
```

**Installation (if proceeding):**
```bash
cp <output>/mesh_config.yaml ~/.openclaw/workspace/mesh-wiring/
cp <output>/asyncapi.yaml ~/.openclaw/workspace/mesh-wiring/
# Wire channels in OpenClaw daemon config
```

**Recommendation for v1:** ⏸️ **DEFER**. Use webhooks for Intake Specialist (direct EIME integration) and lightweight OpenClaw sessions_send for Treasurer cabinet coordination. Full event mesh provides redundancy and cross-cabinet coordination benefits that can be added in v2 when infrastructure is more stable.

---

## Execution Instructions

### Prerequisites
1. OpenClaw workspace created: `~/.openclaw/workspace/cabinet.yaml` ✓
2. Member directories created:
   ```bash
   mkdir -p ~/.openclaw/workspace/{treasurer,budget-owner,finance-staff}
   mkdir -p ~/.openclaw/workspace/treasurer/{queue-guardian,decision-deputy,membranes}
   mkdir -p ~/.openclaw/workspace/treasurer/queue-guardian/skills
   mkdir -p ~/.openclaw/workspace/treasurer/decision-deputy/skills
   mkdir -p ~/.openclaw/workspace/budget-owner/budget-steward/skills
   mkdir -p ~/.openclaw/workspace/finance-staff/intake-specialist/skills
   mkdir -p ~/.openclaw/workspace/mesh-wiring
   ```

3. crewai-skills-architect available and accessible

### Phase A Execution (Parallel)

**Option 1: Manual Invocation (if parallelizing manually)**
```bash
# Terminal 1: Queue Guardian skills
openclaw invoke crewai-skills-architect \
  --manifest delegation-manifest.yaml \
  --delegation treasurer-queue-guardian-skills

# Terminal 2: Decision Deputy skills
openclaw invoke crewai-skills-architect \
  --manifest delegation-manifest.yaml \
  --delegation treasurer-decision-deputy-skills

# Terminal 3: Budget Steward skills
openclaw invoke crewai-skills-architect \
  --manifest delegation-manifest.yaml \
  --delegation budget-owner-steward-skills

# Terminal 4: Intake Specialist skills
openclaw invoke crewai-skills-architect \
  --manifest delegation-manifest.yaml \
  --delegation finance-staff-intake-specialist-skills

# Terminal 5: Membrane design
openclaw invoke membrane-agent-designer \
  --manifest delegation-manifest.yaml \
  --delegation treasurer-cabinet-coordination-membrane
```

**Option 2: Batch Invocation (if OpenClaw supports parallel mode)**
```bash
openclaw invoke-batch \
  --manifest delegation-manifest.yaml \
  --parallel \
  --delegations \
    treasurer-queue-guardian-skills \
    treasurer-decision-deputy-skills \
    budget-owner-steward-skills \
    finance-staff-intake-specialist-skills \
    treasurer-cabinet-coordination-membrane
```

**Expected Duration:** ~45-60 minutes (crewai-skills-architect usually takes 10-15 min per delegation, running in parallel reduces wall-clock time)

### Phase A Verification

After Phase A delegations complete:

```bash
# Check Queen Guardian skills
ls ~/.openclaw/workspace/treasurer/queue-guardian/skills/ | wc -l  # Should be 5

# Check Decision Deputy skills
ls ~/.openclaw/workspace/treasurer/decision-deputy/skills/ | wc -l  # Should be 4

# Check Budget Steward skills
ls ~/.openclaw/workspace/budget-owner/budget-steward/skills/ | wc -l  # Should be 4

# Check Intake Specialist skills
ls ~/.openclaw/workspace/finance-staff/intake-specialist/skills/ | wc -l  # Should be 5

# Check membrane
test -f ~/.openclaw/workspace/treasurer/membranes/queue-guardian-decision-deputy.yaml && echo "✓"
```

### Phase B Execution (Deferred for v1)

If proceeding with cross-cabinet event mesh in v1:

```bash
openclaw invoke redis-mesh-wiring \
  --manifest delegation-manifest.yaml \
  --delegation cross-cabinet-event-mesh-wiring
```

**For v1, skip Phase B.** Proceed directly to "Install Cabinet" below.

---

## Post-Delegation: Install Cabinet

Once Phase A delegations complete and skills are installed:

### 1. Verify All Member Configurations

```bash
# Check cabinet.yaml exists
test -f ~/.openclaw/workspace/cabinet.yaml && echo "✓ cabinet.yaml"

# Check each member has SOUL, AGENTS, TOOLS
for member in treasurer/queue-guardian treasurer/decision-deputy budget-owner/budget-steward finance-staff/intake-specialist; do
  for file in SOUL.md AGENTS.md TOOLS.md; do
    test -f ~/.openclaw/workspace/$member/$file && echo "✓ $member/$file" || echo "✗ MISSING: $member/$file"
  done
done

# Check skills directories are populated
for cabinet in treasurer/queue-guardian treasurer/decision-deputy budget-owner/budget-steward finance-staff/intake-specialist; do
  count=$(ls ~/.openclaw/workspace/$cabinet/skills/*.md 2>/dev/null | wc -l)
  echo "$cabinet: $count SKILL.md files"
done
```

### 2. Start Cabinet Daemon

```bash
# Start OpenClaw daemon
openclaw daemon ~/.openclaw/workspace/cabinet.yaml &

# Verify daemon is listening
sleep 5
openclaw status

# Expected output:
# Cabinet Daemon Status: RUNNING
# Members: 5 registered
#   - queue-guardian (treasurer)
#   - decision-deputy (treasurer)
#   - budget-steward (budget-owner)
#   - intake-specialist (finance-staff)
```

### 3. Register Members

```bash
# Verify all members registered
openclaw members list

# Expected output:
# Registered Members:
# ├─ queue-guardian (treasurer) — status: ready
# ├─ decision-deputy (treasurer) — status: ready
# ├─ budget-steward (budget-owner) — status: ready
# └─ intake-specialist (finance-staff) — status: ready
```

### 4. Test Cabinet Coordination (Smoke Test)

```bash
# Test Queue Guardian → Decision Deputy coordination
openclaw test --scenario "treasurer-escalation" --members queue-guardian decision-deputy

# Expected: Escalation flows correctly from Queue Guardian to Decision Deputy

# Test Budget Steward threshold alert
openclaw test --scenario "budget-threshold" --members budget-steward

# Expected: Threshold alert generated when budget reaches 90%

# Test Intake Specialist screening
openclaw test --scenario "intake-screening" --members intake-specialist

# Expected: Invoice screened, GL suggestion generated, escalation routed correctly
```

### 5. Configure Notification Channels

```bash
# Update cabinet.yaml with SendGrid API key
export SENDGRID_API_KEY="<your-sendgrid-api-key>"

# Update cabinet.yaml with Slack webhook (optional)
export SLACK_WEBHOOK_TREASURY="<your-slack-webhook>"

# Restart daemon to apply config
openclaw daemon restart
```

---

## Success Criteria

✓ **Phase A Complete** when:
- All 5 skill generation delegations produce SKILL.md files
- Membrane configuration file created
- All member directories populated with skills
- `openclaw members list` shows 5 ready members

✓ **Phase B Complete** (if proceeding) when:
- Redis channel configuration wired
- AsyncAPI contracts defined
- Cabinet daemon successfully subscribes to all channels

✓ **Smoke Tests Pass** when:
- Escalation coordination between Queue Guardian and Decision Deputy works
- Budget Steward alerts trigger at thresholds
- Intake Specialist screens invoices and routes escalations correctly

---

## Timeline

| Phase | Duration | Activity |
|-------|----------|----------|
| Phase A (Parallel) | ~1 hour | Invoke 5 delegations simultaneously |
| Verification | ~10 min | Check all files installed |
| Cabinet Installation | ~10 min | Start daemon, register members |
| Smoke Tests | ~15 min | Test escalation, threshold, screening |
| Phase B (Optional) | ~20 min | Wire event mesh (if doing v1) |
| **Total** | **~1.5-2 hours** | End-to-end with Phase A+B |

**Recommended:** Allocate 2-3 hours to Phase A-Installation with buffer for troubleshooting.

---

## Troubleshooting

### Delegation Fails
- Check logs: `openclaw logs <delegation-id>`
- Verify crewai-skills-architect is accessible
- Confirm SKILL.md output directory exists and is writable

### Member Registration Fails
- Check cabinet.yaml syntax: `openclaw validate ~/.openclaw/workspace/cabinet.yaml`
- Verify all member directories exist
- Check SOUL.md, AGENTS.md, TOOLS.md files are valid YAML

### Coordination/Escalation Doesn't Work
- Check OpenClaw daemon logs: `openclaw daemon logs`
- Verify perturbation types match between initiator and responder
- Test directly: `openclaw test --scenario "treasurer-escalation"`

### Skills Don't Load
- Verify SKILL.md files are in correct directory
- Check SKILL.md format against `backend/skills/worker/anomaly_detector/SKILL.md` example
- Run: `openclaw member validate <member-id>`

---

## Dependencies & Notes

**Dependencies Between Phases:**
- Phase A: All 5 delegations are **independent**; can parallelize
- Phase B: Depends on Phase A completion (needs cabinet registered first)
- No dependencies between individual Phase A delegations

**Dependencies Within v1:**
- Intake Specialist routes escalations to EIME pipeline → requires EIME API available
- Budget Steward listens to journal_entry_ready events → requires EIME Redis mesh (or webhook polling as fallback)
- Queue Guardian ↔ Decision Deputy coordination → requires OpenClaw sessions_send (no external dependencies)

**v1 vs v2:**
- **v1:** Use webhooks for Intake Specialist, lightweight OpenClaw for Treasurer cabinet, defer full event mesh to v2
- **v2:** Add cross-cabinet event mesh coordination, full bidirectional event integration with EIME

---

## Next Steps After Installation

1. **Configure Principal Access:** Set up email/Slack notification channels for Treasurer, Budget Owners, Finance Staff
2. **Load Test Data:** Upload 5-10 sample invoices through Intake Specialist to verify screening pipeline
3. **Configure Approval Chains:** Set up approval routing per budget owner and GL account
4. **Wire EIME Integration:** Connect cabinet Redis listeners to EIME event mesh
5. **Monitor & Iterate:** Run for 1 month, collect feedback, refine cabinet policies

