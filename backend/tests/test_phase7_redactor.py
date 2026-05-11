"""Phase 7 redactor tests — privacy class enforcement per RBAC role."""
from __future__ import annotations

import pytest

from backend.membrane.redactor import (
    PrivacyClass,
    PrivacyViolationError,
    Redactor,
    Role,
)


def test_redactor_p0_visible_to_all():
    r = Redactor()
    payload = {"status": "ok"}
    field_classes = {"status": "P0"}
    out, audit = r.redact(payload, field_classes, role=Role.FINANCE_STAFF)
    assert out == {"status": "ok"}
    assert audit["redacted_fields"] == []


def test_redactor_p1_visible_to_finance_staff():
    r = Redactor()
    payload = {"vendor": "ACME"}
    field_classes = {"vendor": "P1"}
    out, audit = r.redact(payload, field_classes, role=Role.FINANCE_STAFF)
    assert out["vendor"] == "ACME"


def test_redactor_p2_hidden_from_finance_staff():
    r = Redactor()
    payload = {"amount": "1000.00", "status": "open"}
    field_classes = {"amount": "P2", "status": "P0"}
    out, audit = r.redact(payload, field_classes, role=Role.FINANCE_STAFF)
    # P2 visible to BUDGET_OWNER+ only
    assert "amount" not in out or out["amount"] == "[REDACTED]"
    assert out["status"] == "open"
    assert "amount" in audit["redacted_fields"]


def test_redactor_p2_visible_to_budget_owner():
    r = Redactor()
    payload = {"amount": "1000.00"}
    field_classes = {"amount": "P2"}
    out, audit = r.redact(payload, field_classes, role=Role.BUDGET_OWNER)
    assert out["amount"] == "1000.00"


def test_redactor_p3_visible_only_to_treasurer_and_admin():
    r = Redactor()
    payload = {"ssn": "111-22-3333"}
    field_classes = {"ssn": "P3"}
    out, audit = r.redact(payload, field_classes, role=Role.TREASURER)
    assert out["ssn"] == "111-22-3333"

    out2, audit2 = r.redact(payload, field_classes, role=Role.ADMIN)
    assert out2["ssn"] == "111-22-3333"


def test_redactor_p3_hidden_from_finance_staff():
    r = Redactor()
    payload = {"ssn": "111-22-3333"}
    field_classes = {"ssn": "P3"}
    out, audit = r.redact(payload, field_classes, role=Role.FINANCE_STAFF)
    assert "ssn" not in out or out["ssn"] == "[REDACTED]"
    assert "ssn" in audit["redacted_fields"]


def test_redactor_strict_mode_raises_on_p3_redaction():
    r = Redactor(strict=True)
    payload = {"ssn": "111-22-3333"}
    field_classes = {"ssn": "P3"}
    with pytest.raises(PrivacyViolationError):
        r.redact(payload, field_classes, role=Role.FINANCE_STAFF)


def test_redactor_invalid_privacy_class_raises():
    r = Redactor()
    with pytest.raises(ValueError):
        r.redact({"x": 1}, {"x": "P9"}, role=Role.ADMIN)


def test_redactor_unknown_field_defaults_to_p1():
    r = Redactor()
    payload = {"vendor": "ACME", "unknown_field": "val"}
    field_classes = {"vendor": "P1"}  # unknown_field not declared
    out, audit = r.redact(payload, field_classes, role=Role.FINANCE_STAFF)
    # Unknown fields default to P1 (operational) and pass through
    assert out["unknown_field"] == "val"


def test_redactor_audit_log_records_role_and_count():
    r = Redactor()
    payload = {"a": 1, "b": 2}
    field_classes = {"a": "P3", "b": "P0"}
    out, audit = r.redact(payload, field_classes, role=Role.FINANCE_STAFF)
    assert audit["role"] == Role.FINANCE_STAFF.value
    assert len(audit["redacted_fields"]) == 1
