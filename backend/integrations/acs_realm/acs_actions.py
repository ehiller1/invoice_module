"""High-level ACS Realm actions (post JE, read recon, etc.)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from backend.models.schemas import JournalEntry


@dataclass
class PostResult:
    success: bool
    acs_reference: Optional[str] = None
    error_message: Optional[str] = None
    screenshot_path: Optional[str] = None
    mock: bool = False


def _is_mock_mode() -> bool:
    """Mock when env says so or when playwright not importable."""
    if os.getenv("EIME_ACS_MOCK") == "1":
        return True
    try:
        import playwright  # type: ignore # noqa: F401
        return False
    except ImportError:
        return True


def _line_field(ln: Any, *names: str, default: Any = Decimal("0")) -> Any:
    """Read first matching field from a Pydantic line model."""
    for n in names:
        if hasattr(ln, n):
            v = getattr(ln, n)
            if v is not None:
                return v
    return default


def _log_mock(je: JournalEntry) -> None:
    log = Path("backend/data/acs_mock_log.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "je_id": getattr(je, "entry_id", None),
        "lines": [
            {
                "account": getattr(ln, "account_number", None),
                "fund": getattr(ln, "fund_id", None),
                "debit": str(_line_field(ln, "debit", "debit_amount")),
                "credit": str(_line_field(ln, "credit", "credit_amount")),
            }
            for ln in getattr(je, "lines", []) or []
        ],
        "would_post_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mock": True,
    }
    with log.open("a") as f:
        f.write(json.dumps(record) + "\n")


def post_journal_entry(je: JournalEntry, church_id: str, headless: bool = True) -> PostResult:
    """Post a journal entry to ACS Realm via browser automation, or mock if not available."""
    if _is_mock_mode():
        _log_mock(je)
        return PostResult(
            success=True,
            acs_reference=f"MOCK-{getattr(je, 'entry_id', 'unknown')}",
            mock=True,
        )

    # Real mode -- needs playwright + credentials + selectors
    from .playwright_runner import PlaywrightSession, SELECTORS

    sel = SELECTORS["journal_entry"]
    try:
        with PlaywrightSession(church_id, headless=headless) as session:
            page = session.page
            page.click(sel["new_entry_button"])
            page.fill(sel["entry_date_field"], str(getattr(je, "entry_date", "")))
            page.fill(
                sel["reference_field"],
                getattr(je, "reference", None) or getattr(je, "entry_id", ""),
            )
            page.fill(sel["memo_field"], getattr(je, "description", "") or "")

            for idx, line in enumerate(je.lines):
                if idx > 0:
                    page.click(sel["add_line_button"])
                page.fill(
                    sel["account_field"].format(idx=idx),
                    getattr(line, "account_number", ""),
                )
                page.fill(
                    sel["fund_field"].format(idx=idx),
                    getattr(line, "fund_id", ""),
                )
                debit = _line_field(line, "debit", "debit_amount")
                credit = _line_field(line, "credit", "credit_amount")
                if Decimal(str(debit)) > 0:
                    page.fill(sel["debit_field"].format(idx=idx), str(debit))
                else:
                    page.fill(sel["credit_field"].format(idx=idx), str(credit))

            page.click(sel["save_button"])
            page.wait_for_selector(sel["confirmation"], timeout=15000)

            return PostResult(success=True, acs_reference=getattr(je, "entry_id", None))
    except Exception as e:
        screenshot = None
        try:
            from .playwright_runner import PlaywrightSession as _PS
            with _PS(church_id, headless=headless) as s:
                screenshot = s.screenshot()
        except Exception:
            pass
        return PostResult(
            success=False,
            error_message=str(e),
            screenshot_path=screenshot,
        )
