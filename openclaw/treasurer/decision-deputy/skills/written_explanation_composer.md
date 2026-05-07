# Written Explanation Composer Skill

**Member:** Decision Deputy (Treasurer's Cabinet)  
**Domain:** Explanation composition, canonical citation, policy reference  
**Model:** claude-sonnet-4-5-20250929  

## Purpose

Compose written explanations for decisions, citing relevant Episcopal canon, fund restrictions, budget policy, and prior board decisions. Adapt tone per audience: formal for Finance Committee, pastoral for Rector, advisory for budget owners.

## Input

```json
{
  "decision": "SPLIT_FUNDS",
  "reason": "budget_overage",
  "primary_gl": "1-5230",
  "secondary_gl": "1-5350",
  "allocation_primary": 800,
  "allocation_secondary": 1600,
  "audience": "finance_committee"
}
```

## Output

```
EXPLANATION — INV-2024-156 Decision

DECISION: APPROVED WITH SPLIT_FUNDS

PLAIN ENGLISH:
This $2,400 facilities maintenance expense will be approved.
It exceeds the available Operating budget, so we will allocate across two funds:
$800 from Operating and $1,600 from Maintenance Contingency.

CANONICAL AUTHORITY:
Episcopal Church Canons permit allocation of expenses across designated funds 
when the expense falls within both funds' purposes (Title I, Canon 7.3).
Facilities maintenance falls within both Operating and Maintenance purposes.

POLICY BASIS:
Holy Comforter budget policy (Vestry-Approved May 2023) permits dual-fund allocation
when single-fund budget is exhausted and the expense is within both funds' purposes.

AUDIT TRAIL:
[Details for Finance Committee record]
```

## Algorithm

```python
async def compose_explanation(
    decision: dict,
    reason: str,
    audience: str
) -> str:
    """Compose decision explanation with canonical authority."""
    
    # Retrieve relevant canon
    canonical_authority = look_up_canonical_authority(reason)
    
    # Retrieve policy references
    policy_references = look_up_church_policies(reason)
    
    # Adapt tone per audience
    tone_map = {
        "finance_committee": "formal",
        "rector": "pastoral",
        "budget_owner": "advisory",
        "vestry": "formal_transparent"
    }
    tone = tone_map.get(audience, "formal")
    
    # Compose sections
    plain_english = compose_plain_english(decision, tone)
    canonical = compose_canonical_section(canonical_authority)
    policy = compose_policy_section(policy_references)
    rationale = compose_rationale(decision, reason, tone)
    
    # Audit trail (for Finance Committee)
    if audience in ["finance_committee", "vestry"]:
        audit = compose_audit_section(decision)
    else:
        audit = ""
    
    return {
        "plain_english": plain_english,
        "canonical_authority": canonical,
        "policy_basis": policy,
        "decision_rationale": rationale,
        "audit_trail": audit
    }
```

## Execution

**Triggered by:** Decision Deputy finalizing decision letter

**Action authority:** Compose and propose; Treasurer approves language

## Example Outputs

**Formal (Finance Committee):**
```
This $2,400 facilities expense will be approved with split allocation:
GL 1-5230: $800 (remaining Operating balance)
GL 1-5350: $1,600 (from Maintenance Contingency)

Canonical Authority: Episcopal Church Canons Title I, Canon 7.3 permit allocation
across designated funds when the expense falls within both funds' purposes.

Policy Basis: Holy Comforter budget policy (Vestry-Approved May 2023) permits
dual-fund allocation when single-fund budget is exhausted and expense is within
both funds' purposes. No fund restriction violation applies.
```

**Pastoral (Rector):**
```
We're approving a $2,400 facilities repair needed for parish accessibility.
This is good stewardship of our physical plant.
The funding is within our maintenance budgets; no canonical concerns.
```

## Testing

- Fund restriction explanation includes canonical authority ✓
- Tone adapts per audience ✓
- Budget overage explanation includes policy basis ✓
- All decisions include audit trail for Finance Committee ✓

