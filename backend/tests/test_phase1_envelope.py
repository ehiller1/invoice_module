"""Phase 1 Foundation tests: Perturbation registry, ImpactSignal envelope,
Distiller base, feature flags.

Verifies FR-IM Phase 1 substrate. Purely additive — no existing code touched.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.membrane import feature_flags
from backend.membrane.distiller import Distiller
from backend.membrane.distiller.base import Distiller as DistillerBase
from backend.membrane.envelope import ImpactSignal
from backend.membrane.perturbations import (
    PERTURBATIONS,
    PRIVACY_CLASSES,
    Perturbation,
    get_perturbation,
)


# ---------------------------------------------------------------------------
# Perturbation registry
# ---------------------------------------------------------------------------

EXPECTED_SIGNALS = {
    59: ("INVOICE_INGESTED", "P1", False),
    60: ("MAPPING_CONFIDENCE_LOW", "P1", False),
    61: ("BUDGET_OVERAGE_RISK", "P1", False),
    62: ("FUND_RESTRICTION_VIOLATION", "P1", False),
    63: ("JOURNAL_ENTRY_READY", "P0", False),
    64: ("PAYMENT_DEDUP_RISK", "P1", False),
    65: ("RECONCILIATION_EXCEPTION", "P1", True),
    66: ("APPROVAL_DEADLINE_PRESSURE", "P1", True),
    67: ("HITL_ESCALATION", "P1", True),
    68: ("POLICY_VIOLATION", "P1", True),
}


def test_all_ten_perturbations_registered():
    assert len(PERTURBATIONS) == 10
    for pid in range(59, 69):
        assert pid in PERTURBATIONS


@pytest.mark.parametrize("pid,expected", list(EXPECTED_SIGNALS.items()))
def test_perturbation_attributes(pid, expected):
    name, privacy, crosses = expected
    p = PERTURBATIONS[pid]
    assert p.id == pid
    assert p.name == name
    assert p.privacy_class == privacy
    assert p.crosses_membrane is crosses
    assert p.default_retention  # non-empty
    assert p.target_channel.startswith("impact:")


def test_invoice_ingested_target_channel():
    assert (
        PERTURBATIONS[59].target_channel
        == "impact:proposed:invoice_ingested"
    )


def test_get_perturbation_by_name():
    assert get_perturbation("INVOICE_INGESTED").id == 59
    assert get_perturbation("POLICY_VIOLATION").id == 68


def test_get_perturbation_unknown_raises():
    with pytest.raises(KeyError):
        get_perturbation("NOT_A_SIGNAL")


def test_privacy_classes_constant():
    assert "P0" in PRIVACY_CLASSES
    assert "P1" in PRIVACY_CLASSES


def test_journal_entry_ready_is_sensitive():
    p = PERTURBATIONS[63]
    assert p.privacy_class == "P0"
    assert p.sensitive is True


# ---------------------------------------------------------------------------
# ImpactSignal envelope
# ---------------------------------------------------------------------------

def _valid_payload(signal_id: int = 59, signal_name: str = "INVOICE_INGESTED"):
    return {
        "envelope_version": "1",
        "signal_id": signal_id,
        "signal_name": signal_name,
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "privacy_class": "P1",
        "crosses_membrane": False,
        "target_channel": "impact:proposed:invoice_ingested",
        "payload": {"foo": "bar"},
        "source": "test",
    }


def test_envelope_valid_construction():
    sig = ImpactSignal(**_valid_payload())
    assert sig.signal_id == 59
    assert sig.envelope_version == "1"


def test_envelope_rejects_missing_required_field():
    bad = _valid_payload()
    del bad["signal_id"]
    with pytest.raises(ValidationError):
        ImpactSignal(**bad)


def test_envelope_rejects_invalid_privacy_class():
    bad = _valid_payload()
    bad["privacy_class"] = "P9"
    with pytest.raises(ValidationError):
        ImpactSignal(**bad)


def test_envelope_rejects_wrong_version():
    bad = _valid_payload()
    bad["envelope_version"] = "2"
    with pytest.raises(ValidationError):
        ImpactSignal(**bad)


def test_envelope_json_schema_file_exists():
    schema_path = (
        Path(__file__).parent.parent / "membrane" / "schemas" / "impact_signal_v1.json"
    )
    assert schema_path.exists()
    schema = json.loads(schema_path.read_text())
    assert schema["$schema"].startswith("http")
    assert schema["title"] == "ImpactSignal"
    # Frozen v1
    assert schema["properties"]["envelope_version"]["const"] == "1"


def test_envelope_validates_against_jsonschema():
    import jsonschema

    schema_path = (
        Path(__file__).parent.parent / "membrane" / "schemas" / "impact_signal_v1.json"
    )
    schema = json.loads(schema_path.read_text())
    jsonschema.validate(instance=_valid_payload(), schema=schema)


def test_envelope_jsonschema_rejects_invalid():
    import jsonschema

    schema_path = (
        Path(__file__).parent.parent / "membrane" / "schemas" / "impact_signal_v1.json"
    )
    schema = json.loads(schema_path.read_text())
    bad = _valid_payload()
    bad["privacy_class"] = "P9"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


@pytest.mark.parametrize("pid", list(EXPECTED_SIGNALS.keys()))
def test_each_perturbation_can_emit_valid_envelope(pid):
    p = PERTURBATIONS[pid]
    payload = {
        "envelope_version": "1",
        "signal_id": p.id,
        "signal_name": p.name,
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "privacy_class": p.privacy_class,
        "crosses_membrane": p.crosses_membrane,
        "target_channel": p.target_channel,
        "payload": {"example": True},
        "source": "test",
    }
    sig = ImpactSignal(**payload)
    assert sig.signal_id == p.id


# ---------------------------------------------------------------------------
# Distiller base
# ---------------------------------------------------------------------------

def test_distiller_is_abstract():
    with pytest.raises(TypeError):
        Distiller()  # type: ignore[abstract]


def test_distiller_subclass_must_implement_distill():
    class Incomplete(Distiller):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_distiller_concrete_subclass_works():
    class Concrete(Distiller):
        def distill(self, raw_event):
            return ImpactSignal(**_valid_payload())

    d = Concrete()
    sig = d.distill({"any": "raw"})
    assert isinstance(sig, ImpactSignal)


def test_distiller_base_reexported():
    assert Distiller is DistillerBase


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def test_feature_flags_have_phase_flags():
    # One flag per phase, keyed to FR-IM references
    for phase in range(1, 7):
        attr = f"PHASE_{phase}_ENABLED"
        assert hasattr(feature_flags, attr), f"missing {attr}"


def test_feature_flags_default_phase1_enabled():
    # Phase 1 substrate should default on
    assert feature_flags.PHASE_1_ENABLED is True


def test_feature_flags_fr_im_mapping():
    mapping = feature_flags.FR_IM_REFERENCES
    assert isinstance(mapping, dict)
    assert 1 in mapping
    assert "FR-IM" in mapping[1]


def test_is_phase_enabled_helper():
    assert feature_flags.is_phase_enabled(1) is True
    assert feature_flags.is_phase_enabled(999) is False
