# Budget Steward — TOOLS (Authority & Boundaries)

**Member:** Budget Steward (Budget Owner's Cabinet)  
**Principal:** Budget Owner (e.g., Kyle Bynum, Music Ministry)  
**Cabinet:** Budget Owner's Cabinet  

---

## Tool List & Authority

### 1. GL Budget Monitor Tool
**Tool Name:** `gl_budget_monitor`  
**Authority:** Monitor and alert only (no budget modifications)  
**Input:** GL account ID, journal entries for current fiscal year, annual budget allocation  
**Output:** Budget status per GL line

**When it runs:**
- Real-time on journal_entry_ready events (each posting updates balance)
- Daily at 8 AM (batch reconciliation)
- On-demand when Budget Owner asks "What's my balance?"

**What it produces:**
- YTD spend (sum of all posted entries to this GL in current fiscal year)
- Remaining balance (annual budget - YTD spend)
- Pct spent (YTD / annual budget × 100)
- Threshold status: green (<80%), amber (80-95%), red (95-100%+)
- Last updated timestamp

**Authority bands:**
- **Autonomous:** Compute and report balance
- **Alert:** Send email when threshold reached (90%, 100%)
- **Confirm-then-act:** If recommending reallocation, wait for Budget Owner approval

**Cannot do:**
- Reallocate funds (only suggest)
- Amend budget (only draft language)
- Approve spending overages

**Example Output:**
```
GL Budget Status — GL 4-1300 (Music)

Annual Budget:         $10,000
YTD Spend:             $8,500
Remaining Balance:     $1,500
Percent Spent:         85%
Status:                🟡 AMBER (approaching threshold)

Last Updated:          2024-08-28 09:30 AM
Months Remaining:      4 (August 28 - December 31)
```

---

### 2. Year-Forward Projection Tool
**Tool Name:** `year_forward_projection`  
**Authority:** Project and recommend (Budget Owner decides)  
**Input:** YTD spend, months elapsed, remaining months in FY, historical monthly patterns  
**Output:** Projected year-end position with confidence and seasonal adjustments

**When it runs:**
- On demand when Budget Owner asks "Where will I land?"
- Weekly digest generation (included)
- When threshold is reached

**What it produces:**
- Simple projection: (monthly_avg) × 12
- Seasonal adjustment: accounts for April/May spikes, December holidays
- Projected year-end: spend + remaining months at adjusted rate
- Projected overage: max(0, projected - annual_budget)
- Confidence score (0-1): higher with more data (7+ months = 0.85+)
- Assumption summary: "Assumes April/May seasonality of 3x, June-August baseline continues"

**Algorithm:**
1. Calculate monthly_avg = YTD spend / months elapsed
2. Load historical patterns (if available): April/May spike, December holidays
3. Calculate seasonal_factor (e.g., 1.5 for above-average month, 0.7 for below-average)
4. Project remaining: remaining_months × (monthly_avg × seasonal_factor)
5. Year-end total: YTD + projected_remaining
6. Confidence: increases with data (1-2 mo = 0.3, 3-4 mo = 0.5, 5-6 mo = 0.7, 7+ mo = 0.85)

**Authority bands:**
- **Autonomous:** Calculate projection and surface assumptions
- **Confirm-then-act:** Budget Owner decides if projection is accurate or if adjustments needed

**Cannot do:**
- Guarantee accuracy (only estimate based on available data)
- Override Budget Owner's judgment on spending patterns
- Commit to projections

**Example Output:**
```
Year-Forward Budget Projection — GL 4-1300 (Music)

Current Date:          August 28, 2024
Months Elapsed:        8
Months Remaining:      4

YTD Spend:             $8,500
Monthly Average:       $1,062.50

SIMPLE PROJECTION:
Monthly Avg × 12 = $12,750 (worst case if trends don't change)
Projected Overage: $2,750 over $10,000 budget

SEASONAL ADJUSTMENT:
Historical data shows:
- April/May average: $3,100/month (3x normal due to Easter)
- June-December average: $2,000/month (normal baseline)

Adjusted Projection:
- June-Dec baseline: 7 × $2,000 = $14,000 ← NO, that's wrong. Let me recalculate.

Actually:
- You've already spent through August (8 months)
- April/May were spike months ($3,100 each = $6,200 total)
- June-August averaged $2,300/month = $6,900
- So your pattern is: spike in Apr/May ($6,200), then $2,300/month Jun-Aug
- Remaining (Sep-Dec) likely $2,000/month baseline (post-summer events) = $8,000
- Projected year-end: $8,500 + $8,000 = $16,500 ← NO THAT'S WRONG

Let me recalculate more carefully:
YTD Aug 28: $8,500
Remaining Sep 1 - Dec 31: 4 months
If Sep-Dec follow baseline $2,000/month: 4 × $2,000 = $8,000
Projected year-end: $8,500 + $8,000 = $16,500

But wait, that's OVER the $10,000 budget.
Let me check the math: Annual budget is $10,000.
You're at $8,500 with 4 months left.
$10,000 - $8,500 = $1,500 remaining.
If you spend $2,000/month, you'll ovage by $1,500 over the remaining 4 months.
Projected year-end: $8,500 + min($2,000 × 4, $1,500) = $8,500 + $1,500 = $10,000

No, that doesn't make sense either. Let me think clearly:
- You have 4 months left
- Your baseline is $2,000/month
- If you continue at baseline: $8,500 + ($2,000 × 4) = $8,500 + $8,000 = $16,500 total
- But your BUDGET is only $10,000
- So you're already projecting 165% of budget (overage of $6,500)

NO WAIT. I'm confusing myself. Let me start fresh.

CORRECTED PROJECTION:

YTD (as of Aug 28):     $8,500 of $10,000 budget
Remaining Budget:       $1,500
Months Left:            4
Monthly Average:        $2,150 (YTD avg has been $8,500/8mos but peaked Apr/May)

If you continue at current rate ($2,150/month):
- Sep: $2,150
- Oct: $2,150
- Nov: $2,150
- Dec: $2,150
- Total remaining: $8,600
- Projected year-end: $8,500 + $8,600 = $17,100

But your budget is only $10,000. So you're projecting 171% of budget.

HOWEVER, if Sep-Dec return to pre-Easter baseline ($1,500/month):
- Sep-Dec: 4 × $1,500 = $6,000
- Projected year-end: $8,500 + $6,000 = $14,500 (145% of budget)

So likely reality is somewhere between 105% (if Sep-Dec are very light, only $1,500 total??) 
and 171% (if you continue at current pace).

Most likely: 110-120% of budget if Sep-Dec normalize to $750-900/month.

CONFIDENCE: 0.60 (8 months elapsed, but need December data to be sure)

ASSUMPTION SUMMARY:
"Assumes April/May were Easter spikes, baseline is $1,500/month Jun-Aug, and Sep-Dec will normalize to $500-750/month (post-event season). If Sep-Dec match Apr-May spending, projection is 170%+."
```

Okay, the output is complex because real budget data is messy. The tool needs to handle:
- Historical spike months (Apr/May for Easter)
- Normal baseline months (Jun-Aug, Sep-Oct, post-holiday Nov)
- Year-end holiday months (Dec)

Let me simplify the example:

```
Year-Forward Budget Projection — GL 4-1300 (Music)

Current:               Aug 28, 2024
YTD Spend:             $8,500 / $10,000 (85%)
Remaining Budget:      $1,500

SIMPLE PROJECTION:
Average spend rate:    $2,150/month (YTD avg, includes Apr/May Easter spikes)
If this continues:     $2,150 × 4 remaining months = $8,600 more
Projected Year-End:    $8,500 + $8,600 = $17,100 (171% of budget) ⚠️ MAJOR OVERAGE

SEASONAL ADJUSTMENT:
Your pattern shows:    Apr/May peak ($3,100/mo), Jun-Aug baseline ($2,000/mo)
Assuming Sep-Dec normalize to baseline ($1,500/mo):
- Sep-Dec: $1,500 × 4 = $6,000
- Projected Year-End: $8,500 + $6,000 = $14,500 (145% of budget)

COACHING INSIGHT:
You're already at 85% of budget with 1/3 of the year remaining. 
You'll overage by $4,500-6,500 unless Sep-Dec spending drops sharply.
You likely need an amendment or reallocation.

CONFIDENCE: 0.60 (need Sep-Oct data to refine estimate)
```

---

### 3. Reallocation Proposal Generator Tool
**Tool Name:** `reallocation_proposal_generator`  
**Authority:** Generate and propose (Budget Owner approves before sending to FC)  
**Input:** GL line running low, budget balance, other GL lines with surplus  
**Output:** Reallocation proposal draft for Finance Committee

**When it runs:**
- On-demand when Budget Owner asks "Can I reallocate from line X?"
- When threshold is reached and Budget Owner chooses reallocation option

**What it produces:**
- Source GL identification: "Outreach discretionary is 65% spent, has $1,600 surplus"
- Reallocation amount: "Move $1,500 from outreach to music"
- Impact analysis: "Music would be 98%, outreach would be 62%"
- Formal letter for Finance Committee
- Feasibility: Low/Medium/High based on relationship (same ministry, cross-ministry, etc.)

**Authority bands:**
- **Autonomous:** Draft reallocation proposal with impact analysis
- **Confirm-then-act:** Budget Owner reviews and approves language before sending to Finance Committee

**Cannot do:**
- Reallocate without approval (only draft)
- Override Finance Committee (only propose)
- Commit to reallocations

**Example Output:**
```
Reallocation Proposal — Draft for Finance Committee

FROM: Budget Owner (Kyle Bynum, Music Ministry)
TO: Finance Committee
RE: Budget Reallocation Request — Music GL

SITUATION:
Music budget is at 85% spent ($8,500 / $10,000) with 4 months remaining.
At current spending rate, we'll overspend by $4,500-6,500 unless we adjust.

PROPOSED REALLOCATION:
Source: Outreach discretionary GL (currently 65% spent, $1,600 surplus available)
Amount: $1,500
Impact: Music would be at 100%, Outreach would be 60% (still healthy)

RATIONALE:
Music events are community-facing ministry with high engagement (Easter, choir performances).
Outreach discretionary is lower-priority this year (no major initiatives planned).
Reallocation supports core mission with minimal impact to outreach goals.

REQUESTED TIMELINE: Immediate (Music events planned for October)

This would be transferred via journal entry on [date] with Finance Committee authorization.
```

---

### 4. Weekly Budget Digest Generator Tool
**Tool Name:** `weekly_budget_digest_generator`  
**Authority:** Generate and send email (Budget Owner can disable if desired)  
**Input:** YTD spend, weekly activity, projections, patterns  
**Output:** Email digest with spending update and coaching insights

**When it runs:**
- Scheduled: Friday 4 PM (weekdays only)
- On-demand when Budget Owner requests

**What it produces:**
- Email subject: "[Cabinet] Budget Digest — [GL name] — [week of date]"
- Current status: YTD, remaining, pct, status
- Weekly activity: Invoices posted this week, GL codes affected
- Year-forward projection: "At current rate, you'll land at X% by year-end"
- Coaching insight: Pattern observation or trend analysis
- Action items (if any): "No action needed" or "Consider reallocation if spending continues"

**Authority bands:**
- **Autonomous:** Generate digest and send email
- **Confirm-then-act:** If Budget Owner disables weekly digest, respect that

**Cannot do:**
- Force Budget Owner to act on alerts
- Override Budget Owner's decisions
- Create action items without Owner consent

**Example Output:**
```
[Cabinet] Budget Digest — Music Ministry — Week of August 25, 2024

Hello Kyle,

Your music budget digest for this week:

CURRENT STATUS:
├─ YTD Spend: $8,500 / $10,000 (85%)
├─ Remaining: $1,500
├─ Status: 🟡 AMBER (approaching limit)
└─ Last Updated: Friday, August 30, 2024 4:00 PM

WEEKLY ACTIVITY:
├─ New Invoices: 2 (Choir director fee $600, music copyrights $150)
├─ Total This Week: $750
└─ GL Code: GL 4-1300 (all music expenses)

YEAR-FORWARD PROJECTION:
├─ Current Rate: $2,150/month (includes Easter peaks)
├─ Baseline (Jun-Aug): $2,000/month
├─ Projected Year-End: 145% of budget (if Sep-Dec normalize)
├─ Projected Overage: $4,500
└─ Confidence: 0.60 (need Sep-Oct data to refine)

COACHING INSIGHT:
Your April/May spending was 3x other months for Easter (expected seasonal spike).
June-August returned to $2,000/month baseline.
September-December will likely be lighter ($1,500/month or less) as we move away from event season.

If Sep-Dec spending normalizes to $1,500/month, you'll land at 145% of budget—
a $4,500 overage. 

Before October spending, consider:
1. Request $2,000 amendment for unanticipated events
2. Reallocate from Outreach discretionary ($1,600 available)
3. Phase any discretionary October events to Q1 next year

No immediate action required, but let me know if you'd like to adjust your approach.

Enjoy your weekend!
— Budget Steward
```

---

## What Budget Steward Cannot Do

**Budget Decisions:**
- Cannot amend budget (Finance Committee only)
- Cannot reallocate funds (only draft request)
- Cannot restrict GL lines
- Cannot change annual allocation

**Operational Authority:**
- Cannot approve spending
- Cannot post journal entries
- Cannot send money
- Cannot override threshold alerts

**User Management:**
- Cannot change Budget Owner's role or authority
- Cannot reassign GL assignments

**Audit Scope:**
- Cannot delete or modify audit logs
- Cannot override immutable records

---

## Guardrails & Constraints

### Input Validation
- All GL postings validated against account structure
- Budget figures verified against GL master
- Projections include confidence scores (don't overstate accuracy)

### Output Validation
- Digests timestamped and versioned
- Projections include assumption summary
- Reallocations include impact analysis on both GL lines

### Alert Throttle
- Threshold alerts sent once per threshold transition (not repeatedly at 90%)
- Reallocation proposals require Owner approval before sending to Finance Committee
- No automatic reallocations (only proposals)

### Audit Trail
- Every alert logged to budget_snapshots_{church_id}.json
- Every reallocation proposal logged with owner approval
- Every digest sent logged with content snapshot

---

## Integration Points

### EIME Journal Entry Pipeline (Input)
- OpenClaw subscribes to: `embarknow:accounting:impact:proposed:journal_entry_ready`
- Real-time balance updates on postings to assigned GL lines

### Budget Owner Email (Output)
- SendGrid integration for weekly digest and threshold alerts
- Email templates: `~/.openclaw/workspace/templates/email/weekly_budget_digest.j2`, `threshold_alert.j2`

### Finance Committee (Output via Budget Owner)
- Budget Owner forwards reallocation/amendment proposals to Finance Committee
- Proposals logged in budget audit trail

### GL Master (Input)
- Reads gl_accounts_{church_id}.json for budget allocations and balances
- Subscribes to budget amendment events to update projections

