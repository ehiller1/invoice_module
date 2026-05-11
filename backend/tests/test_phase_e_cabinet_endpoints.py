"""Phase E: Tests for cabinet endpoint route consolidation and church_id scoping.

These tests verify:
1. Phase 5 mock cabinet activity/approve/disavow endpoints are removed.
2. Phase 12 endpoints require church_id in request body (no hardcoded "holy_comforter").
3. backend/routes/cabinets.py router is mounted in the app.
4. backend/routes/cabinets.py no longer references "default-church".
"""
from __future__ import annotations

import inspect
from typing import Any, List


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_app_routes() -> List[Any]:
    """Return raw `routes` list from the main FastAPI app."""
    from backend.main import app
    return list(app.routes)


def _routes_matching(method: str, path: str) -> List[Any]:
    """Find all routes registered for a given (method, path)."""
    matches = []
    for r in _get_app_routes():
        # FastAPI APIRoute objects have `methods` and `path` attrs.
        methods = getattr(r, "methods", set()) or set()
        rpath = getattr(r, "path", None)
        if rpath == path and method.upper() in methods:
            matches.append(r)
    return matches


# ---------------------------------------------------------------------------
# Step 1: Phase 5 mock cabinet endpoints removed
# ---------------------------------------------------------------------------

class TestPhase5MockEndpointsRemoved:
    """Phase 5 mock cabinet endpoints should be removed from main.py."""

    def test_no_mock_activity_in_main_source(self):
        """The hardcoded mock activity payload from Phase 5 should be removed."""
        from backend import main as main_module

        src = inspect.getsource(main_module)
        # The Phase 5 mock contained the hardcoded subject — confirm it is gone.
        assert "Approved reallocation of Legacy Scholarship to Active Mission" not in src, (
            "Phase 5 mock activity endpoint should be deleted"
        )
        assert "Quasi-endowment draw policy amendment" not in src, (
            "Phase 5 mock activity endpoint should be deleted"
        )

    def test_no_phase5_approve_stub(self):
        """The Phase 5 stub /approve endpoint (no item_id) should be removed."""
        # The Phase 5 stub returned 'led_<hex>' as a fake ledger_entry_id.
        from backend import main as main_module

        src = inspect.getsource(main_module)
        assert "Decision {action} recorded in audit ledger" not in src, (
            "Phase 5 approve stub should be deleted"
        )

    def test_no_phase5_disavow_stub(self):
        """The Phase 5 stub /disavow endpoint should be removed."""
        from backend import main as main_module

        src = inspect.getsource(main_module)
        # Distinctive Phase 5 stub message
        assert "Override disavowed. Original decision path restored" not in src, (
            "Phase 5 disavow stub should be deleted"
        )

    def test_no_duplicate_activity_route(self):
        """After removing Phase 5 mock, only one GET activity route should remain."""
        matches = _routes_matching("GET", "/api/cabinets/{principal}/activity")
        assert len(matches) == 1, (
            f"Expected exactly one activity route, got {len(matches)}"
        )


# ---------------------------------------------------------------------------
# Step 2: Phase 12 endpoints no longer hardcode church_id
# ---------------------------------------------------------------------------

class TestPhase12NoHardcodedChurchId:
    """Phase 12 cabinet endpoints must take church_id from request body."""

    def test_main_py_has_no_hardcoded_holy_comforter_in_cabinet_section(self):
        """The string "holy_comforter" should not appear in cabinet endpoint code."""
        from backend import main as main_module

        src = inspect.getsource(main_module)
        # We do not search the entire file (other tests may legitimately reference
        # "holy_comforter"), but at minimum confirm the literal does not appear
        # immediately above approve/reject cabinet calls.
        # Specifically: `get_decision_ledger("holy_comforter")` should be gone
        # from the cabinet approve/reject endpoints.
        offending = 'get_decision_ledger("holy_comforter")'
        # Find all cabinet endpoint sections and ensure none use the hardcoded value.
        # Conservative check: confirm hardcoded literal absent from the file.
        assert offending not in src, (
            f"Found hardcoded {offending} in main.py — should be from request body"
        )


# ---------------------------------------------------------------------------
# Step 3: backend/routes/cabinets.py is mounted
# ---------------------------------------------------------------------------

class TestCabinetsRouterMounted:
    """backend/routes/cabinets.py router should be mounted in main app."""

    def test_router_is_included_in_app(self):
        """The cabinets router from backend.routes should be in app.routes."""
        from backend.main import app
        from backend.routes import cabinets as cabinets_route_module

        # Each route function in the cabinets router should appear in app.routes.
        router_endpoint_funcs = {
            getattr(r, "endpoint", None)
            for r in cabinets_route_module.router.routes
        }
        router_endpoint_funcs.discard(None)
        assert router_endpoint_funcs, "Router should declare at least one endpoint"

        app_endpoint_funcs = {
            getattr(r, "endpoint", None) for r in app.routes
        }
        # At least one of the router's endpoints should appear in the app.
        overlap = router_endpoint_funcs & app_endpoint_funcs
        assert overlap, (
            f"backend/routes/cabinets.py router endpoints not mounted in main app. "
            f"Router exports: {[f.__name__ for f in router_endpoint_funcs]}"
        )


# ---------------------------------------------------------------------------
# Step 4: backend/routes/cabinets.py no longer uses "default-church"
# ---------------------------------------------------------------------------

class TestRoutesCabinetsNoHardcodedChurchId:
    """The standalone router should not hardcode church_id."""

    def test_no_default_church_literal(self):
        """The literal 'default-church' should not appear in cabinets.py."""
        from backend.routes import cabinets as cabinets_route_module

        src = inspect.getsource(cabinets_route_module)
        assert '"default-church"' not in src, (
            "Found 'default-church' literal in backend/routes/cabinets.py"
        )
        assert "'default-church'" not in src, (
            "Found 'default-church' literal in backend/routes/cabinets.py"
        )

    def test_approve_endpoint_requires_church_id(self):
        """The approve endpoint source should reference body.get('church_id')."""
        from backend.routes import cabinets as cabinets_route_module

        src = inspect.getsource(cabinets_route_module.approve_cabinet_decision)
        assert "church_id" in src, (
            "approve_cabinet_decision should reference church_id"
        )
        # Should validate via HTTPException 400 when missing.
        assert "400" in src or "HTTPException" in src

    def test_reject_endpoint_requires_church_id(self):
        """The reject endpoint source should reference body.get('church_id')."""
        from backend.routes import cabinets as cabinets_route_module

        src = inspect.getsource(cabinets_route_module.reject_cabinet_decision)
        assert "church_id" in src, (
            "reject_cabinet_decision should reference church_id"
        )
        assert "400" in src or "HTTPException" in src


# ---------------------------------------------------------------------------
# Behavioural test: app starts without warnings / duplicate routes
# ---------------------------------------------------------------------------

class TestAppStartup:
    """Verify the app can be imported and exposes expected cabinet routes."""

    def test_app_imports(self):
        """The main FastAPI app should import cleanly."""
        from backend.main import app
        assert app is not None

    def test_expected_cabinet_routes_exist(self):
        """All expected cabinet routes should be registered."""
        from backend.main import app

        registered_paths = {
            (tuple(sorted(getattr(r, "methods", set()) or set())), getattr(r, "path", None))
            for r in app.routes
        }
        # The activity GET endpoint should exist.
        assert any(
            path == "/api/cabinets/{principal}/activity" and "GET" in methods
            for methods, path in registered_paths
        )
        # Approve/reject endpoints (Phase 12 form with item_id) should exist.
        assert any(
            path == "/api/cabinets/{principal}/items/{item_id}/approve"
            and "POST" in methods
            for methods, path in registered_paths
        )
        assert any(
            path == "/api/cabinets/{principal}/items/{item_id}/reject"
            and "POST" in methods
            for methods, path in registered_paths
        )
