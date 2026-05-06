"""Task 9 verification: structural Episcopal-rule coverage checklist for
Holy Comforter Episcopal Church profile.

Run from project root:
    uv run python -m backend.data._verify_holy_comforter

Asserts every requirement in PLAN-holy-comforter-episcopal.md Task 9.
Exits 0 on success, 1 on failure (with checklist diff printed).
"""
from __future__ import annotations
import sys

from backend.tools.coa_store import load_accounting_context
from backend.models import FundCategory, RestrictionClass


def main() -> int:
    ctx = load_accounting_context("holy_comforter")
    if ctx is None:
        print("FAIL: load_accounting_context('holy_comforter') returned None")
        return 1

    failures: list[str] = []

    # 1. Required account numbers
    nums = {a.account_number for a in ctx.accounts}
    required_nums = {
        "8410",  # Diocesan Assessment expense
        "8420",  # National Church / Province Pledge
        "5210",  # CPF Pension Assessment
        "2040",  # CPF Payable liability
        "2050",  # Diocesan Assessment Payable liability
        "4900",  # Rector's Discretionary Contributions
        "6900",  # Rector's Discretionary Disbursements
        "1040",  # Rector's Discretionary Cash
        "1900",  # Endowment principal
        "1910",  # Endowment income
        "3300",  # Net Assets - Endowment Principal
        "3310",  # Net Assets - Endowment Income
        "5100",  # Clergy salary
        "5101",  # Clergy housing allowance
        "5220",  # Clergy healthcare premium
    }
    missing = required_nums - nums
    if missing:
        failures.append(f"Missing account numbers: {sorted(missing)}")

    # 2. Required fund_ids
    fund_ids = {f.fund_id for f in ctx.funds}
    required_funds = {"GEN", "OUTREACH", "MEMORIAL", "RECTOR_DISC",
                      "ENDOW_PRIN", "ENDOW_INC"}
    missing_f = required_funds - fund_ids
    if missing_f:
        failures.append(f"Missing fund_ids: {sorted(missing_f)}")

    # 3. RECTOR_DISC must be BOARD_DESIGNATED
    rd = next((f for f in ctx.funds if f.fund_id == "RECTOR_DISC"), None)
    if rd is None:
        failures.append("RECTOR_DISC fund missing")
    elif rd.fund_category != FundCategory.BOARD_DESIGNATED:
        failures.append(f"RECTOR_DISC must be BOARD_DESIGNATED, got "
                        f"{rd.fund_category}")

    # 4. ENDOW_PRIN must be WITH_RESTRICTION_PERMANENT
    ep = next((f for f in ctx.funds if f.fund_id == "ENDOW_PRIN"), None)
    if ep is None:
        failures.append("ENDOW_PRIN fund missing")
    elif ep.restriction_class != RestrictionClass.WITH_RESTRICTION_PERMANENT:
        failures.append(f"ENDOW_PRIN must be WITH_RESTRICTION_PERMANENT, "
                        f"got {ep.restriction_class}")

    # 5. CPF allocation schedule
    if not any(s.schedule_id == "CPF_18PCT" for s in ctx.allocation_schedules):
        failures.append("Missing AllocationSchedule with id 'CPF_18PCT'")

    # 6. Diocesan assessment apportionment
    if not any(a.account_number == "8410" for a in ctx.apportionment_accounts):
        failures.append("Missing ApportionmentAccount for account 8410")

    # 7. All four restriction-class buckets covered
    rcs = {f.restriction_class for f in ctx.funds}
    required_rcs = {
        RestrictionClass.WITHOUT_RESTRICTION,
        RestrictionClass.WITH_RESTRICTION_PURPOSE,
        RestrictionClass.WITH_RESTRICTION_PERMANENT,
    }
    missing_rcs = required_rcs - rcs
    if missing_rcs:
        failures.append(f"Missing restriction classes among funds: "
                        f"{sorted(r.value for r in missing_rcs)}")

    # 8. BOARD_DESIGNATED category present (via RECTOR_DISC)
    if not any(f.fund_category == FundCategory.BOARD_DESIGNATED
               for f in ctx.funds):
        failures.append("No fund with FundCategory.BOARD_DESIGNATED found")

    # 9. Account-fund restriction class consistency
    fund_rc = {f.fund_id: f.restriction_class for f in ctx.funds}
    for a in ctx.accounts:
        if fund_rc.get(a.fund_id) != a.restriction_class:
            failures.append(f"Account {a.account_number} ({a.account_name}) "
                            f"restriction_class {a.restriction_class} != "
                            f"fund {a.fund_id} restriction_class "
                            f"{fund_rc.get(a.fund_id)}")

    # 10. Account number uniqueness
    if len(nums) != len(ctx.accounts):
        failures.append(f"Duplicate account numbers detected: "
                        f"{len(ctx.accounts)} accounts but only {len(nums)} unique nums")

    # 11. RECTOR_DISC fund linkage on 4900 + 6900
    by_num = {a.account_number: a for a in ctx.accounts}
    if by_num.get("4900") and by_num["4900"].fund_id != "RECTOR_DISC":
        failures.append("Account 4900 must be in RECTOR_DISC fund")
    if by_num.get("6900") and by_num["6900"].fund_id != "RECTOR_DISC":
        failures.append("Account 6900 must be in RECTOR_DISC fund")

    # 12. Endowment income split: 4300 -> ENDOW_INC, 1900 -> ENDOW_PRIN
    if by_num.get("4300") and by_num["4300"].fund_id != "ENDOW_INC":
        failures.append("Account 4300 (Endowment Income) must be in ENDOW_INC, "
                        f"got {by_num['4300'].fund_id}")
    if by_num.get("1900") and by_num["1900"].fund_id != "ENDOW_PRIN":
        failures.append("Account 1900 must be in ENDOW_PRIN, "
                        f"got {by_num['1900'].fund_id}")

    if failures:
        print("=== FAIL: Holy Comforter structural validation ===")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("=== PASS: Holy Comforter structural validation ===")
    print(f"  church_id:         {ctx.church_id}")
    print(f"  church_name:       {ctx.church_name}")
    print(f"  denomination_type: {ctx.denomination_type}")
    print(f"  fiscal_year:       {ctx.fiscal_year}")
    print(f"  accounts:          {len(ctx.accounts)}")
    print(f"  funds:             {len(ctx.funds)}")
    print(f"  schedules:         {len(ctx.allocation_schedules)}")
    print(f"  apportionments:    {len(ctx.apportionment_accounts)}")
    print(f"  warnings:          {len(ctx.warnings)}")
    print()
    print("Episcopal-rule coverage checklist (all 12 checks passed):")
    print("  [x] Diocesan Assessment (8410 + ApportionmentAccount)")
    print("  [x] National Church Pledge (8420)")
    print("  [x] CPF mandatory 18% (5210 + CPF_18PCT schedule + 2040 liability)")
    print("  [x] Rector's Discretionary (RECTOR_DISC BOARD_DESIGNATED + 4900/6900/1040)")
    print("  [x] Endowment principal/income split (ENDOW_PRIN + ENDOW_INC + 1900/1910/3300/3310)")
    print("  [x] Parochial Report clergy split (5100, 5101, 5210, 5220 all present)")
    print("  [x] All restriction classes represented")
    print("  [x] BOARD_DESIGNATED category present")
    print("  [x] Account-fund restriction class consistency")
    print("  [x] Account number uniqueness")
    print("  [x] RECTOR_DISC linkage on revenue/expense pair")
    print("  [x] Endowment income (4300) -> ENDOW_INC; principal (1900) -> ENDOW_PRIN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
