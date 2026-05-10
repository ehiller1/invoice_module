"""CoA grounding validator (Phase 5b).

The vision treats the chart of accounts as a **tag dictionary**, not a
destination grid. Every account reference produced by an LLM (or any other
system component) MUST be validated against the church's seeded CoA before
the response is allowed to ship. This catches the Flow 3 hallucination
class of failure: the QA path returning "5100 (Utilities)" when the seeded
CoA says 5100 = Clergy Salary.

The validator is the only place that turns a free-text or numeric account
reference into an authoritative tag. Callers should treat its output as
the canonical answer.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# A "5100" or "5100 Utilities" or "Account 5100" reference.
# Numeric prefix is required so we don't false-positive on dollar amounts —
# we accept 4–6 digit account numbers, which covers the seeded 4-digit
# numbering plus headroom for sub-accounts.
_ACCOUNT_REF_RE = re.compile(r"\b(\d{4,6})(?!\d)")


def _accounts_from_ctx(ctx: Any) -> List[Dict[str, str]]:
    """Extract a normalized account list from any AccountingContext shape.

    Each row carries both `number`/`name` (used by the validator) and
    `account_number`/`account_name`/`fund_id`/`fund_name` (used by the
    downstream JE builder). Keeping both keys avoids a second lookup
    when the validator's match is fed straight into a JournalEntryLine.
    """
    if ctx is None:
        return []
    # AccountingContext uses `.accounts`; older codepaths used `.chart_of_accounts`.
    accounts = (
        getattr(ctx, "accounts", None)
        or getattr(ctx, "chart_of_accounts", None)
        or []
    )
    out: List[Dict[str, str]] = []
    for a in accounts:
        num = str(getattr(a, "account_number", "") or "")
        nm = str(getattr(a, "account_name", "") or "")
        fund_id = str(getattr(a, "fund_id", "") or "")
        fund_name = str(getattr(a, "fund_name", "") or "")
        if num:
            out.append({
                "number": num,
                "name": nm,
                "account_number": num,
                "account_name": nm,
                "fund_id": fund_id,
                "fund_name": fund_name,
            })
    return out


def lookup_account(ctx: Any, number_or_name: str) -> Optional[Dict[str, str]]:
    """Resolve a reference (number OR name) against the church's seeded CoA.

    Returns the matching account dict, or None if no match. Numeric matches
    require an exact account_number; name matches are case-insensitive
    substring lookups against account_name.
    """
    if not number_or_name:
        return None
    needle = number_or_name.strip()
    accounts = _accounts_from_ctx(ctx)
    # Exact numeric match first.
    if needle.isdigit():
        for a in accounts:
            if a["number"] == needle:
                return a
        return None
    # Name match (case-insensitive, allow substring).
    lower = needle.lower()
    for a in accounts:
        if a["name"].lower() == lower:
            return a
    for a in accounts:
        if lower in a["name"].lower():
            return a
    return None


def find_account_references(text: str) -> List[str]:
    """Return numeric account references that appear in `text`.

    Uses a word-boundary regex on 4–6 digit numbers. Dollar amounts written
    with a `$` prefix are excluded by stripping `$\\d+(\\.\\d+)?` first.
    """
    if not text:
        return []
    # Strip dollar amounts so $247.50 doesn't masquerade as account "247".
    cleaned = re.sub(r"\$\s*\d[\d,]*(?:\.\d+)?", " ", text)
    return list({m.group(1) for m in _ACCOUNT_REF_RE.finditer(cleaned)})


def validate_text_grounding(ctx: Any, text: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """Scan free-form text for account references; report any that are not
    in the seeded CoA OR whose surrounding label disagrees with the CoA.

    Returns (ok, problems). `problems` is a list of dicts:
        {"reference": "5100", "issue": "missing"|"label_mismatch",
         "claimed_label": "Utilities", "actual_label": "Clergy Salary",
         "suggestion": {"number": "...", "name": "..."} | None}

    The label-mismatch heuristic looks for "<number> <words>" or
    "<number> (<words>)" patterns within ~40 chars of the number, and
    compares the words against the seeded account name.
    """
    problems: List[Dict[str, Any]] = []
    if not text or ctx is None:
        return True, problems

    seen = set()
    cleaned = re.sub(r"\$\s*\d[\d,]*(?:\.\d+)?", " ", text)
    for m in _ACCOUNT_REF_RE.finditer(cleaned):
        ref = m.group(1)
        if ref in seen:
            continue
        seen.add(ref)
        actual = lookup_account(ctx, ref)
        if actual is None:
            problems.append({
                "reference": ref,
                "issue": "missing",
                "claimed_label": None,
                "actual_label": None,
                "suggestion": None,
            })
            continue

        # Label-mismatch check: peek at up to ~40 chars after the number.
        tail_start = m.end()
        tail = cleaned[tail_start:tail_start + 40]
        # Common shapes: "5100 Utilities", "5100 - Utilities", "5100 (Utilities)"
        lm = re.match(r"\s*[\-:\(]*\s*([A-Za-z][A-Za-z &/\-]{2,})", tail)
        if lm:
            claimed = lm.group(1).strip(" )-:")
            if claimed and claimed.lower() not in actual["name"].lower() \
               and actual["name"].lower() not in claimed.lower():
                # Try to find a better-matching account by the claimed label.
                better = lookup_account(ctx, claimed)
                problems.append({
                    "reference": ref,
                    "issue": "label_mismatch",
                    "claimed_label": claimed,
                    "actual_label": actual["name"],
                    "suggestion": better,
                })

    return (len(problems) == 0), problems


def ground_je_slot(
    ctx: Any,
    hint: str,
    fund_filter: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Resolve a JE slot hint against the seeded CoA.

    Returns (account_dict, error). On success, error is None. On failure,
    error is a short human-readable explanation suitable for the chat reply.
    """
    if not hint:
        return None, "Empty account hint."
    # If the hint is purely numeric, require an exact match — never a
    # near-miss, which is what produced the Flow 3 hallucination.
    if hint.strip().isdigit():
        match = lookup_account(ctx, hint.strip())
        if match is None:
            return None, (
                f"GL account {hint.strip()} is not in the seeded chart of "
                f"accounts. Please use a number that exists for this church."
            )
        return match, None
    # Otherwise fall back to name lookup. Caller may still escalate to
    # a semantic search after this returns no result.
    match = lookup_account(ctx, hint)
    if match is None:
        return None, None  # signal "try semantic_search"
    return match, None
