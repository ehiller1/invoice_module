"""
Phase 3.9 — Mobile / Tablet Responsive UI (FR-10.5)

These tests are static-asset checks: we confirm that the responsive
infrastructure is present in the served HTML/JS/CSS bundles. They do
NOT spin up a real browser (no Playwright dependency). For full
visual verification, see thoughts/handoffs/.../task-03-phase-3.9-responsive.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ----------------------------------------------------------------
# Static asset routing
# ----------------------------------------------------------------
def test_responsive_css_served_with_correct_mime(client: TestClient) -> None:
    r = client.get("/responsive.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert len(r.content) > 100


def test_eime_responsive_js_served(client: TestClient) -> None:
    r = client.get("/eime-responsive.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]


def test_eime_shell_js_served(client: TestClient) -> None:
    r = client.get("/eime-shell.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]


# ----------------------------------------------------------------
# Shell-level responsive structure
# ----------------------------------------------------------------
def test_shell_html_has_responsive_breakpoints() -> None:
    html = (FRONTEND / "_shell.html").read_text()
    # Three-panel layout uses lg: breakpoint
    assert "lg:flex" in html or "lg:block" in html
    # Mobile chat FAB
    assert 'id="eime-chat-fab"' in html
    # Mobile nav backdrop + chat backdrop
    assert 'id="eime-nav-backdrop"' in html
    assert 'id="eime-chat-backdrop"' in html
    # Touch-safe mobile top bar buttons
    assert 'min-h-[44px]' in html


def test_shell_js_has_breakpoint_handler() -> None:
    js = (FRONTEND / "eime-shell.js").read_text()
    assert "_adjustToBreakpoint" in js
    assert "toggleNav" in js
    assert "toggleChat" in js
    # responsive.css auto-injection
    assert "responsive.css" in js
    # Swipe-to-dismiss bottom sheet
    assert "_wireChatSwipeDismiss" in js or "touchend" in js
    # Escape key handling
    assert "Escape" in js


def test_shell_js_loads_responsive_css() -> None:
    js = (FRONTEND / "eime-shell.js").read_text()
    assert "data-eime-responsive" in js


# ----------------------------------------------------------------
# Legacy-page responsive injection
# ----------------------------------------------------------------
LEGACY_PAGES = [
    "index.html",
    "jobs.html",
    "budget.html",
    "coa.html",
    "chat.html",
    "skills.html",
]


@pytest.mark.parametrize("page", LEGACY_PAGES)
def test_legacy_page_includes_responsive_css(page: str) -> None:
    html = (FRONTEND / page).read_text()
    assert "/responsive.css" in html, f"{page} is missing responsive.css link"


@pytest.mark.parametrize("page", LEGACY_PAGES)
def test_legacy_page_includes_responsive_js(page: str) -> None:
    html = (FRONTEND / page).read_text()
    assert "/eime-responsive.js" in html, f"{page} is missing eime-responsive.js"


@pytest.mark.parametrize("page", LEGACY_PAGES)
def test_legacy_page_has_viewport_meta(page: str) -> None:
    html = (FRONTEND / page).read_text()
    assert "viewport" in html
    assert "width=device-width" in html


# ----------------------------------------------------------------
# Responsive CSS contents
# ----------------------------------------------------------------
def test_responsive_css_collapses_legacy_sidebar() -> None:
    css = (FRONTEND / "responsive.css").read_text()
    # Hide hardcoded w-64 sidebar below lg
    assert "max-width: 1023.98px" in css
    assert "aside.w-64" in css
    assert "display: none" in css


def test_responsive_css_has_touch_targets() -> None:
    css = (FRONTEND / "responsive.css").read_text()
    # 44px minimum touch target
    assert "min-height: 44px" in css


def test_responsive_css_prevents_horizontal_scroll() -> None:
    css = (FRONTEND / "responsive.css").read_text()
    assert "overflow-x: hidden" in css
    assert "max-width: 100vw" in css


def test_responsive_css_has_drawer_primitives() -> None:
    css = (FRONTEND / "responsive.css").read_text()
    assert ".eime-rsv-drawer" in css
    assert ".eime-rsv-backdrop" in css
    assert ".eime-rsv-fab" in css
    assert ".eime-rsv-topbar" in css


# ----------------------------------------------------------------
# Responsive JS behavior
# ----------------------------------------------------------------
def test_responsive_js_clones_legacy_sidebar() -> None:
    js = (FRONTEND / "eime-responsive.js").read_text()
    assert "findLegacySidebar" in js
    assert "cloneNode" in js
    # Skips when shell already mounted
    assert "isShellPage" in js
    # Touch / swipe handling
    assert "touchstart" in js
    assert "touchend" in js
    # Escape-key close
    assert "Escape" in js


def test_responsive_js_emits_chat_fab() -> None:
    js = (FRONTEND / "eime-responsive.js").read_text()
    assert "eime-rsv-fab" in js
    # Skips chat FAB on chat.html itself
    assert "/chat.html" in js


# ----------------------------------------------------------------
# Shell pages: rendered HTML still parses (sanity)
# ----------------------------------------------------------------
SHELL_PAGES = [
    "/jes.html",
    "/payments.html",
    "/knowledge-base.html",
    "/treasurer-queue.html",
    "/settings/approval-chains.html",
    "/settings/model-config.html",
]


@pytest.mark.parametrize("path", SHELL_PAGES)
def test_shell_page_serves_200(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200
    assert "EIMEShell.mount" in r.text
