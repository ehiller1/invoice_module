"""Manages a Playwright browser session for ACS Realm (FR-06.5).

Soft-imports `playwright` so that the rest of the system (and CI) keeps
working when the browser dependency is not installed. Mock-mode in
`acs_actions.post_journal_entry` short-circuits before this module is needed.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    from playwright.sync_api import sync_playwright as _sync_playwright  # type: ignore
    sync_playwright: Any = _sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:                                          # pragma: no cover
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright: Any = None

from .credentials import retrieve

SELECTORS = yaml.safe_load(
    (Path(__file__).parent / "selectors.yaml").read_text()
)


class PlaywrightSession:
    """Headless Playwright browser scoped to a single church login."""

    def __init__(self, church_id: str, headless: bool = True, creds: Optional[dict] = None) -> None:
        self.church_id = church_id
        self.headless = headless
        self.creds = creds or retrieve(church_id)
        if not self.creds:
            raise RuntimeError(
                f"No ACS credentials stored for {church_id}"
            )
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self.page: Any = None

    def __enter__(self) -> "PlaywrightSession":
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright not installed — set EIME_ACS_MOCK=1 or "
                "`uv pip install playwright && playwright install chromium`"
            )
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self.page = self._context.new_page()
        self._login()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass

    def _login(self) -> None:
        sel = SELECTORS["login"]
        assert self.creds is not None
        self.page.goto(f"{self.creds['base_url']}/login")
        self.page.fill(sel["username_field"], self.creds["username"])
        self.page.fill(sel["password_field"], self.creds["password"])
        self.page.click(sel["submit_button"])
        self.page.wait_for_selector(sel["success_indicator"], timeout=15000)

    def screenshot(self, path: Optional[str] = None) -> str:
        path = path or (
            f"backend/data/screenshots/{self.church_id}_{int(time.time())}.png"
        )
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=path)
        return path
