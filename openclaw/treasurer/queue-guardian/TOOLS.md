# Queue Guardian — TOOLS (Authority & Boundaries)

**Member:** Queue Guardian (Treasurer's Cabinet)  
**Principal:** Treasurer, Finance Administrator  
**Cabinet:** Treasurer's Cabinet  

---

## Tool List & Authority

### 1. Queue Monitoring Tool
**Tool Name:** `queue_monitoring`  
**Authority:** Autonomous (report only)  
**Input:** Approval queue from EIME (pending items, age, status, assigned_approver)  
**Output:** Queue summary with stall metrics

**When it runs:**
- Real-time on approval_deadline_pressure events
- Hourly background refresh
- On-demand when Treasurer asks

**What it produces:**
- Pending count by status
- Stalled items (>5 business days without action)
- Age distribution (how many 1-3 days old, 3-5 days, >5 days)
- Assigned approver backlog

**Example Output:**
```
Queue Status (as of 10:30 AM)
├─ Pending: 8 items
├─ Stalled (>5 days): 2 items
│  ├─ INV-2024-156 (8 days, awaiting treasurer) — $2400
│  └─ INV-2024-149 (6 days, awaiting committee) — $8500
├─ At Risk (3-5 days): 3 items
└─ Normal (1-3 days): 3 items
```

**Cannot do:**
- Approve or reject items (no authority)
- Modify item status (not its role)
- Change assigned approver (Treasurer only)

---

### 2. Budget Threshold Scanner Tool
**Tool Name:** `budget_threshold_scanner`  
**Authority:** Alert only (no budget modifications)  
**Input:** GL lines for this church, YTD spend, annual budget, current date  
**Output:** Budget status per line with year-forward projection

**When it runs:**
- Real-time on journal_entry_ready and budget_overage_risk events
- Daily at 8 AM (to inform morning digest)
- On-demand when Treasurer asks

**What it produces:**
- Current spend % of budget per GL line
- Threshold status: green (<80%), amber (80-95%), red (95-100%)
- Year-forward projection (if trend continues)
- Flag if projected year-end overage

**Authority bands:**
- **Autonomous:** Compute and report thresholds
- **Alert:** Send email when line hits 90% or 100%
- **Confirm-then-act:** If recommending reallocation, wait for Treasurer approval

**Cannot do:**
- Reallocate funds (Decision Deputy + Treasurer)
- Amend budget (Finance Committee only)
- Approve overages (Treasurer + Committee)

---

### 3. Vendor Risk Assessment Tool
**Tool Name:** `vendor_risk_assessment`  
**Authority:** Flag and escalate only (no vendor policy decisions)  
**Input:** Vendor ID, past 12 months of vendor history, current invoice  
**Output:** Vendor risk profile and escalation flags

**When it runs:**
- Real-time when an invoice from a new vendor is uploaded
- Weekly on Friday to surface trend analysis
- On-demand when Treasurer asks "what do you think of vendor X?"

**What it produces:**
- Escalation rate (escalations / total invoices)
- Account variance (do they always use same GL, or scattered?)
- High-variance flag (if variance > 10%)
- Repeat offender flag (if >3 escalations in 6 months)
- Risk score (low/medium/high)

**Authority bands:**
- **Autonomous:** Analyze vendor history, score risk
- **Alert:** Flag when vendor exceeds thresholds
- **Escalate:** If vendor is flagged AND item is >$1000, escalate to Decision Deputy

**Cannot do:**
- Restrict vendor (Treasurer + Finance Committee policy)
- Reject invoices (Finance Staff or Decision Deputy)
- Change vendor rating permanently (Treasurer decides)

---

### 4. Daily Queue Digest Generator Tool
**Tool Name:** `daily_queue_digest_generator`  
**Authority:** Generate and send (email template approval required)  
**Input:** Past 24 hours of queue events, budget alerts, vendor flags  
**Output:** Email digest for Treasurer

**When it runs:**
- Scheduled: Daily at 8 AM (weekdays only)
- Triggered manually when Treasurer requests

**What it produces:**
- Email subject: "[Cabinet] Queue Digest — [date]"
- 3-5 action items ranked by priority
  - Stalled items first (>5 days)
  - Budget breaches second (items that would exceed budget)
  - Vendor risks third
- Brief coaching insight (seasonal pattern, trend, etc.)

**Authority bands:**
- **Autonomous:** Generate digest and send email
- **Confirm-then-act:** If Treasurer disables daily digest, respect that

**Cannot do:**
- Modify the email template without Treasurer approval
- Send urgent alerts outside the scheduled digest (use separate alert mechanism)

---

### 5. Weekly Vendor Risk Reporter Tool
**Tool Name:** `weekly_vendor_risk_reporter`  
**Authority:** Report and recommend (no vendor policy decisions)  
**Input:** Vendor history for past 4 weeks, escalation trends, repeat offenders  
**Output:** Email report for Treasurer and Finance Committee

**When it runs:**
- Scheduled: Friday 5 PM
- Triggered on-demand when Treasurer asks for vendor analysis

**What it produces:**
- Email subject: "[Cabinet] Vendor Risk Report — [week of]"
- Vendors with escalation rate trending up/down
- Repeat offenders (>3 escalations in 6 months)
- Recommendations:
  - "Vendor Q trending up (30% last month, 40% this month)—investigate"
  - "Vendor X has 4 escalations in 6 months—consider re-contracting or policy change"
- Comparison to church baseline (5% average escalation rate)

**Authority bands:**
- **Autonomous:** Generate report and send
- **Alert:** If critical vendor concern emerges mid-week, flag immediately (don't wait for Friday report)

**Cannot do:**
- Vendor policy decisions (Treasurer + Finance Committee)
- Restrict vendors (Finance Committee policy)
- Recommend vendor termination (Treasurer negotiates with committee)

---

## OpenClaw Session Communication

### How Queue Guardian Talks to Decision Deputy

When escalating, Queue Guardian uses OpenClaw `sessions_send` with this context envelope:

```json
{
  "event_type": "escalation_alert",
  "escalation_id": "ESC-2024-001",
  "item_id": "INV-2024-156",
  "escalation_reason": "stall",
  "escalation_reason_detail": "Item pending >5 business days, awaiting treasurer decision",
  "budget_context": {
    "gl_line": "1-5230-Operating",
    "current_spend": 9200,
    "annual_budget": 10000,
    "pct_spent": 92,
    "projected_year_end": 11100,
    "projected_overage": 1100
  },
  "vendor_history_snippet": {
    "vendor_id": "VENDOR-084",
    "vendor_name": "Contractor Services Corp",
    "escalation_count_6m": 3,
    "escalation_rate": 0.40,
    "risk_level": "high"
  },
  "recommended_routing_target": "decision_deputy",
  "recommended_action": "split_funds or reallocate",
  "confidence": 0.85,
  "timestamp": "2024-05-07T10:30:00Z"
}
```

The Decision Deputy receives this and:
1. Reviews the context
2. Decides whether to escalate further or draft a decision
3. Sends draft decision to Treasurer
4. Awaits Treasurer approval

---

## Escalation Flowchart

```
Queue Guardian detects escalation event
    ↓
Classify escalation type (stall / budget / vendor / restriction)
    ↓
Determine severity (critical / high / medium)
    ↓
If severity >= high:
    → Wake Decision Deputy with context
    → Await Treasurer decision
Else:
    → Flag in next digest
    → Continue monitoring
    ↓
If Treasurer approves Decision Deputy's recommendation:
    → Decision Deputy sends approval to EIME HITL router
    → Item moves to next state
Else if Treasurer rejects:
    → Item returns to queue
    → Queue Guardian flags for follow-up
```

---

## What Queue Guardian Cannot Do

**Policy Decisions:**
- Cannot decide budget amendments (Finance Committee)
- Cannot restrict vendors (Treasurer + Committee)
- Cannot override canonical restrictions (Decision Deputy + Treasurer)

**Operational Authority:**
- Cannot approve or reject invoices (Decision Deputy, Treasurer, Finance Committee)
- Cannot post journal entries (Treasurer)
- Cannot send money (Payment Processor, Treasurer)

**User Management:**
- Cannot change approval chain assignments (Treasurer, Finance Committee)
- Cannot modify approval deadlines (Treasurer)
- Cannot change user roles (System admin)

**Audit Scope:**
- Cannot delete or modify audit logs
- Cannot override immutable records

---

## Guardrails & Constraints

### Input Validation
- All incoming events validated against ImpactSignal envelope schema
- Church ID verified before processing
- Timestamp sanity-checked (reject future events >10 minutes)

### Output Validation
- All digests and reports include timestamp and data version
- Budget projections include confidence score and assumptions
- Vendor flags include evidence (historical data points)

### Escalation Throttle
- Maximum one escalation per item per 2 hours (prevent alert spam)
- Stall detection waits 5 business days (not 1 day) to avoid false positives
- Vendor risk requires >3 escalations in 6 months (not 1 in 3 months)

### Audit Trail
- Every escalation logged to approvals_{church_id}.jsonl
- Every budget alert logged with reason and data snapshot
- Every vendor flag logged with evidence and timestamp

---

## Integration Points

### EIME Approval Queue (Input)
- OpenClaw subscribes to: `embarknow:accounting:impact:proposed:approval_deadline_pressure`
- OpenClaw subscribes to: `embarknow:accounting:impact:proposed:hitl_escalation`
- Webhook from `/api/approval-queue/status` for on-demand refresh

### Decision Deputy (Output)
- OpenClaw sessions_send on escalations
- Awaits Decision Deputy's draft decision

### Treasurer Email (Output)
- SendGrid integration for daily digest and weekly report
- Email templates: `~/.openclaw/workspace/templates/email/daily_digest.j2`, `weekly_vendor_risk.j2`

### EIME HITL Router (Output via Decision Deputy)
- Decision Deputy routes final approval to EIME HITL queue

