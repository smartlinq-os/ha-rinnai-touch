"""Offline tests for the Rinnai status model.

All payloads are synthetic and fictional: no captures, addresses, real room
names, credentials, identifiers, or household data. Frames are built through
the real parser so the model is exercised end-to-end, with no network access
and no Home Assistant imports.
"""

from __future__ import annotations

import ast
import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from custom_components.rinnai_touch.models import (
    RinnaiStatusModel,
    StatusSnapshot,
)
from custom_components.rinnai_touch.protocol import ParsedFrame, RinnaiFrameParser

# --- synthetic payload builders ---------------------------------------------

FULL_SYST: dict[str, object] = {
    "SYST": {
        "CFG": {"MTSP": "N", "TU": "C", "ZA": "Living ", "ZB": "   "},
        "AVM": {"HG": "Y", "CG": "N", "EC": "N"},
        "OSS": {"MD": "H", "ST": "N"},
        "FLT": {"AV": "N"},
    }
}

COOL_SYST: dict[str, object] = {
    "SYST": {
        "AVM": {"HG": "N", "CG": "Y", "EC": "N"},
        "OSS": {"MD": "C", "ST": "N"},
    }
}

EVAP_SYST: dict[str, object] = {
    "SYST": {
        "AVM": {"HG": "N", "CG": "N", "EC": "Y"},
        "OSS": {"MD": "E", "ST": "N"},
    }
}

HGOM_FULL: dict[str, object] = {
    "HGOM": {
        "CFG": {"ZUIS": "Y", "ZAIS": "Y", "ZBIS": "N"},
        "OOP": {"ST": "N", "FL": "08"},
        "ZUS": {"MT": "223", "AE": "Y"},
        "ZAS": {"MT": "999", "AE": "N"},
        "ZAO": {"UE": "Y", "OP": "A", "SP": "20", "AO": "N"},
    }
}

CGOM_FULL: dict[str, object] = {
    "CGOM": {
        "CFG": {"ZAIS": "Y"},
        "ZAS": {"MT": "241", "AE": "Y"},
    }
}

ECOM_FULL: dict[str, object] = {
    "ECOM": {
        "CFG": {"ZAIS": "Y"},
        "GSS": {"BY": "N"},
        "ZAS": {"MT": "255", "AE": "N"},
    }
}


def syst_oss(mode: str, state: str = "N") -> dict[str, object]:
    """A minimal SYST group carrying only operating mode and state."""
    return {"SYST": {"OSS": {"MD": mode, "ST": state}}}


def make_frame(sequence: int, payload: list[dict[str, object]]) -> ParsedFrame:
    """Build a ParsedFrame by running real wire bytes through the parser."""
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    frames = RinnaiFrameParser().feed(f"N{sequence:06d}{text}".encode())
    assert len(frames) == 1
    return frames[0]


def apply_payloads(
    model: RinnaiStatusModel, *payloads: list[dict[str, object]]
) -> StatusSnapshot:
    """Apply payloads as sequence-numbered frames; return the last snapshot."""
    snapshot: StatusSnapshot | None = None
    for sequence, payload in enumerate(payloads, start=1):
        snapshot = model.apply(make_frame(sequence, payload))
    assert snapshot is not None
    return snapshot


@pytest.fixture
def model() -> RinnaiStatusModel:
    return RinnaiStatusModel()


# --- 1-3: complete payloads per mode ----------------------------------------


def test_full_syst_and_hgom_payload(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, [FULL_SYST, HGOM_FULL])
    assert snapshot.operating_mode == "H"
    assert snapshot.controller_state == "N"
    assert snapshot.active_mode_group == "HGOM"
    assert snapshot.capabilities.heater_observed is True
    assert snapshot.capabilities.cooler_observed is False
    assert snapshot.capabilities.temperature_unit == "C"
    assert list(snapshot.zones) == ["U", "A", "B"]  # stable letter order
    zone_u = snapshot.zones["U"]
    assert zone_u.installed_observed is True
    assert zone_u.current is not None
    assert zone_u.current.measured_temperature == 22.3
    assert zone_u.current.auto_enabled is True
    zone_a = snapshot.zones["A"]
    assert zone_a.current is not None
    assert zone_a.current.measured_temperature is None  # 999 sentinel
    assert zone_a.current.user_enabled_raw == "Y"
    assert zone_a.current.control_mode_raw == "A"
    assert zone_a.current.setpoint_raw == "20"
    assert zone_a.current.schedule_override_raw == "N"
    assert snapshot.zones["B"].installed_observed is False


def test_syst_and_cgom_payload(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, [COOL_SYST, CGOM_FULL])
    assert snapshot.operating_mode == "C"
    assert snapshot.active_mode_group == "CGOM"
    assert snapshot.capabilities.cooler_observed is True
    assert snapshot.capabilities.heater_observed is False
    zone_a = snapshot.zones["A"]
    assert zone_a.installed_observed is True
    assert zone_a.current is not None
    assert zone_a.current.measured_temperature == 24.1


def test_syst_and_ecom_payload(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, [EVAP_SYST, ECOM_FULL])
    assert snapshot.operating_mode == "E"
    assert snapshot.active_mode_group == "ECOM"
    assert snapshot.capabilities.evaporative_observed is True
    zone_a = snapshot.zones["A"]
    assert zone_a.current is not None
    assert zone_a.current.measured_temperature == 25.5
    assert zone_a.current.auto_enabled is False


# --- 4-8: raw group retention and replacement -------------------------------


def test_unknown_top_level_group_is_retained(model: RinnaiStatusModel) -> None:
    mystery: dict[str, object] = {"XGOM": {"MYSTERY": {"Q": "1"}}}
    snapshot = apply_payloads(model, [FULL_SYST, mystery])
    assert snapshot.raw_groups["XGOM"] == {"MYSTERY": {"Q": "1"}}
    assert "Q" not in snapshot.zones  # unknown groups never manufacture zones


def test_later_syst_replaces_prior_syst_exactly(
    model: RinnaiStatusModel,
) -> None:
    snapshot = apply_payloads(model, [FULL_SYST], [syst_oss("H")])
    assert snapshot.raw_groups["SYST"] == {"OSS": {"MD": "H", "ST": "N"}}
    # No deep merge: earlier CFG/AVM/FLT subgroups are gone from raw data.
    assert "CFG" not in snapshot.raw_groups["SYST"]
    assert "AVM" not in snapshot.raw_groups["SYST"]
    assert "FLT" not in snapshot.raw_groups["SYST"]


def test_mode_group_replacement_leaves_other_groups(
    model: RinnaiStatusModel,
) -> None:
    replacement: dict[str, object] = {"HGOM": {"ZUS": {"MT": "230"}}}
    snapshot = apply_payloads(model, [FULL_SYST, HGOM_FULL], [replacement])
    assert snapshot.raw_groups["HGOM"] == {"ZUS": {"MT": "230"}}
    assert snapshot.raw_groups["SYST"] == FULL_SYST["SYST"]
    zone_u = snapshot.zones["U"]
    assert zone_u.current is not None
    assert zone_u.current.measured_temperature == 23.0
    # Zone A has no data in the replaced HGOM: no current claim, but its
    # cumulative installation observation is untouched.
    assert snapshot.zones["A"].current is None
    assert snapshot.zones["A"].installed_observed is True


def test_syst_only_frame_after_full_frame(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, [FULL_SYST, HGOM_FULL], [FULL_SYST])
    # HGOM is retained raw data and remains the active group under MD=H.
    zone_u = snapshot.zones["U"]
    assert zone_u.current is not None
    assert zone_u.current.measured_temperature == 22.3
    assert list(snapshot.zones) == ["U", "A", "B"]


def test_mode_group_only_frame_after_syst_frame(
    model: RinnaiStatusModel,
) -> None:
    snapshot = apply_payloads(model, [FULL_SYST], [HGOM_FULL])
    assert snapshot.operating_mode == "H"
    assert snapshot.active_mode_group == "HGOM"
    zone_u = snapshot.zones["U"]
    assert zone_u.current is not None
    assert zone_u.current.measured_temperature == 22.3


# --- 9-11: cumulative observations survive ----------------------------------


def test_capabilities_survive_partial_later_frames(
    model: RinnaiStatusModel,
) -> None:
    snapshot = apply_payloads(model, [FULL_SYST], [syst_oss("H")])
    assert snapshot.capabilities.heater_observed is True
    assert snapshot.capabilities.temperature_unit == "C"


def test_multi_setpoint_observation_survives_omission(
    model: RinnaiStatusModel,
) -> None:
    mtsp_syst: dict[str, object] = {"SYST": {"CFG": {"MTSP": "Y"}}}
    snapshot = apply_payloads(model, [mtsp_syst], [syst_oss("H")])
    assert snapshot.capabilities.multi_setpoint_observed is True


def test_zone_installation_survives_mode_change_and_omission(
    model: RinnaiStatusModel,
) -> None:
    other_mode: dict[str, object] = {"CGOM": {"CFG": {"ZBIS": "Y"}}}
    snapshot = apply_payloads(
        model, [FULL_SYST, HGOM_FULL], [syst_oss("C"), other_mode]
    )
    assert snapshot.zones["A"].installed_observed is True  # from HGOM earlier
    assert snapshot.zones["B"].installed_observed is True  # from CGOM now


def test_installed_latch_survives_later_n_flag(
    model: RinnaiStatusModel,
) -> None:
    uninstall: dict[str, object] = {"HGOM": {"CFG": {"ZAIS": "N"}}}
    snapshot = apply_payloads(model, [FULL_SYST, HGOM_FULL], [uninstall])
    # Removal requires validated evidence or user reconfiguration, neither
    # of which exists in Phase 1: the observation stays latched.
    assert snapshot.zones["A"].installed_observed is True


def test_capability_latch_survives_later_n_flag(
    model: RinnaiStatusModel,
) -> None:
    available: dict[str, object] = {
        "SYST": {"AVM": {"HG": "Y"}, "OSS": {"MD": "H"}}
    }
    unavailable: dict[str, object] = {"SYST": {"AVM": {"HG": "N"}}}
    snapshot = apply_payloads(model, [available], [unavailable])
    # Latest raw layer reports exactly the replacement frame: the explicit
    # N is visible, and unrelated earlier fields (OSS) are not retained.
    assert snapshot.raw_groups["SYST"]["AVM"]["HG"] == "N"
    assert snapshot.raw_groups["SYST"] == {"AVM": {"HG": "N"}}
    assert "OSS" not in snapshot.raw_groups["SYST"]
    # Historical observation stays latched despite the explicit later N.
    assert snapshot.capabilities.heater_observed is True


# --- 12-15: zone identity and names ------------------------------------------


def test_zone_u_uses_fallback_name_common(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, [{"HGOM": {"CFG": {"ZUIS": "Y"}}}])
    assert snapshot.zones["U"].name == "Common"


def test_zones_a_to_d_use_fallback_names(model: RinnaiStatusModel) -> None:
    flags: dict[str, object] = {"HGOM": {"CFG": {"ZBIS": "N", "ZCIS": "Y"}}}
    snapshot = apply_payloads(model, [flags])
    assert snapshot.zones["B"].name == "Zone B"
    assert snapshot.zones["C"].name == "Zone C"


def test_controller_zone_names_are_trimmed(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, [FULL_SYST])
    assert snapshot.zones["A"].name == "Living"


def test_whitespace_name_does_not_replace_known_name(
    model: RinnaiStatusModel,
) -> None:
    blank_name: dict[str, object] = {"SYST": {"CFG": {"ZA": "   "}}}
    rename: dict[str, object] = {"SYST": {"CFG": {"ZA": "Lounge"}}}
    snapshot = apply_payloads(model, [FULL_SYST], [blank_name])
    assert snapshot.zones["A"].name == "Living"
    snapshot = model.apply(make_frame(3, [rename]))
    assert snapshot.zones["A"].name == "Lounge"  # most recent non-empty wins


# --- 16-20: measured temperature handling ------------------------------------


def zone_a_temperature_payloads(mt: object) -> list[list[dict[str, object]]]:
    """Payload sequence putting an MT value into the active mode group."""
    sensed: dict[str, object] = {"HGOM": {"ZAS": {"MT": mt}}}
    if mt is None:
        sensed = {"HGOM": {"ZAS": {"AE": "Y"}}}
    return [[syst_oss("H")], [sensed]]


def test_mt_numeric_string_converts_from_tenths(
    model: RinnaiStatusModel,
) -> None:
    snapshot = apply_payloads(model, *zone_a_temperature_payloads("223"))
    zone = snapshot.zones["A"]
    assert zone.current is not None
    assert zone.current.measured_temperature == 22.3
    assert zone.current.raw_measured_temperature == "223"


def test_mt_integer_converts_from_tenths(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, *zone_a_temperature_payloads(223))
    zone = snapshot.zones["A"]
    assert zone.current is not None
    assert zone.current.measured_temperature == 22.3
    assert zone.current.raw_measured_temperature == "223"


@pytest.mark.parametrize("sentinel", ["999", 999])
def test_mt_no_reading_sentinel_is_none(
    model: RinnaiStatusModel, sentinel: object
) -> None:
    snapshot = apply_payloads(model, *zone_a_temperature_payloads(sentinel))
    zone = snapshot.zones["A"]
    assert zone.current is not None
    assert zone.current.measured_temperature is None
    assert zone.current.raw_measured_temperature == "999"


@pytest.mark.parametrize("invalid", ["abc", "", "22.3", True])
def test_invalid_mt_values_become_none(
    model: RinnaiStatusModel, invalid: object
) -> None:
    snapshot = apply_payloads(model, *zone_a_temperature_payloads(invalid))
    zone = snapshot.zones["A"]
    assert zone.current is not None
    assert zone.current.measured_temperature is None


def test_missing_mt_remains_none(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, *zone_a_temperature_payloads(None))
    zone = snapshot.zones["A"]
    assert zone.current is not None
    assert zone.current.measured_temperature is None
    assert zone.current.raw_measured_temperature is None
    assert zone.current.auto_enabled is True


# --- 21-22: current state comes only from the active mode group --------------


def test_current_zone_data_only_from_active_mode_group(
    model: RinnaiStatusModel,
) -> None:
    heat_data: dict[str, object] = {"HGOM": {"ZAS": {"MT": "223"}}}
    cool_data: dict[str, object] = {"CGOM": {"ZAS": {"MT": "555"}}}
    snapshot = apply_payloads(model, [syst_oss("H"), heat_data, cool_data])
    zone = snapshot.zones["A"]
    assert zone.current is not None
    assert zone.current.measured_temperature == 22.3  # HGOM, not stale CGOM
    snapshot = model.apply(make_frame(2, [syst_oss("C")]))
    zone = snapshot.zones["A"]
    assert zone.current is not None
    assert zone.current.measured_temperature == 55.5  # CGOM is active now


def test_no_current_zone_data_without_known_operating_mode(
    model: RinnaiStatusModel,
) -> None:
    snapshot = apply_payloads(model, [{"HGOM": {"ZAS": {"MT": "223"}}}])
    # The zone is an observed fact, but with no SYST.OSS.MD there is no
    # active mode group and therefore no claimed current status.
    assert snapshot.zones["A"].current is None
    assert snapshot.active_mode_group is None


@pytest.mark.parametrize("mode", ["R", "N", "Q"])
def test_r_n_and_unknown_modes_claim_no_active_group(
    model: RinnaiStatusModel, mode: str
) -> None:
    snapshot = apply_payloads(model, [syst_oss(mode), HGOM_FULL])
    assert snapshot.operating_mode == mode
    assert snapshot.active_mode_group is None
    assert snapshot.zones["U"].current is None  # HGOM data is not "current"


# --- 23-24: fault handling ----------------------------------------------------


@pytest.mark.parametrize(
    ("flag", "expected"), [("Y", True), ("N", False), ("X", None)]
)
def test_fault_active_flag_maps_safely(
    model: RinnaiStatusModel, flag: str, expected: bool | None
) -> None:
    payload: dict[str, object] = {"SYST": {"FLT": {"AV": flag}}}
    snapshot = apply_payloads(model, [payload])
    assert snapshot.fault.active is expected


def test_missing_fault_group_maps_to_unknown(model: RinnaiStatusModel) -> None:
    snapshot = apply_payloads(model, [syst_oss("H")])
    assert snapshot.fault.active is None
    assert snapshot.fault.code_raw is None


def test_optional_fault_fields_preserved_without_interpretation(
    model: RinnaiStatusModel,
) -> None:
    fault: dict[str, object] = {
        "SYST": {"FLT": {"AV": "Y", "GP": "H", "UT": "01", "TP": "L", "CD": "C6"}}
    }
    snapshot = apply_payloads(model, [fault])
    assert snapshot.fault.active is True
    assert snapshot.fault.appliance_raw == "H"
    assert snapshot.fault.unit_raw == "01"
    assert snapshot.fault.severity_raw == "L"
    assert snapshot.fault.code_raw == "C6"


def test_unknown_fault_keys_survive_in_raw_groups(
    model: RinnaiStatusModel,
) -> None:
    fault: dict[str, object] = {"SYST": {"FLT": {"AV": "Y", "ZZ": "odd"}}}
    snapshot = apply_payloads(model, [fault])
    assert snapshot.raw_groups["SYST"]["FLT"]["ZZ"] == "odd"


# --- 25-26: raw retention and empty payloads ---------------------------------


def test_unknown_nested_fields_survive_in_raw_groups(
    model: RinnaiStatusModel,
) -> None:
    weird_syst: dict[str, object] = {
        "SYST": {"OSS": {"MD": "H"}, "WEIRD": {"X": "1"}}
    }
    weird_zone: dict[str, object] = {"HGOM": {"ZQX": {"MT": "1"}}}
    snapshot = apply_payloads(model, [weird_syst, weird_zone])
    assert snapshot.raw_groups["SYST"]["WEIRD"] == {"X": "1"}
    assert snapshot.raw_groups["HGOM"]["ZQX"] == {"MT": "1"}
    assert "Q" not in snapshot.zones  # non-standard letters are raw-only


def test_empty_payload_updates_sequence_only(model: RinnaiStatusModel) -> None:
    first = apply_payloads(model, [FULL_SYST, HGOM_FULL])
    second = model.apply(make_frame(42, []))
    assert second.sequence == 42
    assert dict(second.raw_groups) == dict(first.raw_groups)
    assert second.capabilities == first.capabilities
    assert dict(second.zones) == dict(first.zones)


# --- 27-28: mutation safety ---------------------------------------------------


def test_snapshot_mutation_cannot_affect_model_or_future_snapshots(
    model: RinnaiStatusModel,
) -> None:
    snapshot = apply_payloads(model, [FULL_SYST, HGOM_FULL])
    with pytest.raises(TypeError):
        snapshot.raw_groups["SYST"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.zones["A"] = snapshot.zones["U"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        snapshot.zones["A"].name = "Hacked"  # type: ignore[misc]
    # Nested raw structures are the caller's private deep copy: mutating
    # them must not leak into model state or future snapshots.
    snapshot.raw_groups["SYST"]["OSS"]["MD"] = "X"
    later = model.apply(make_frame(9, []))
    assert later.operating_mode == "H"
    assert later.raw_groups["SYST"]["OSS"]["MD"] == "H"
    assert later.zones["A"].name == "Living"


def test_parsed_frame_payload_is_not_mutated(model: RinnaiStatusModel) -> None:
    frame = make_frame(1, [FULL_SYST, HGOM_FULL])
    payload_before = copy.deepcopy(frame.payload)
    model.apply(frame)
    model.apply(make_frame(2, [syst_oss("C")]))
    assert frame.payload == payload_before


# --- 29-30: import hygiene and command-surface absence ------------------------


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    return imported


def test_model_imports_no_networking_or_home_assistant_modules() -> None:
    models_path = (
        Path(__file__).resolve().parent.parent
        / "custom_components"
        / "rinnai_touch"
        / "models.py"
    )
    imported = _top_level_imports(models_path)
    assert not imported & {"socket", "aiohttp", "homeassistant", "asyncio"}


def test_model_exposes_no_command_functionality() -> None:
    banned = ("command", "send", "write", "keepalive", "queue")
    for obj in (RinnaiStatusModel, StatusSnapshot):
        for attribute in dir(obj):
            lowered = attribute.lower()
            assert not any(word in lowered for word in banned), attribute


# --- additional policy locks ---------------------------------------------------


def test_zone_seen_only_in_sensed_group_is_observed_not_installed(
    model: RinnaiStatusModel,
) -> None:
    # Documented policy: sensed data alone is evidence the zone exists as an
    # observed fact, but never a claim that it is installed.
    snapshot = apply_payloads(model, [syst_oss("H"), {"HGOM": {"ZCS": {"MT": "201"}}}])
    zone = snapshot.zones["C"]
    assert zone.installed_observed is False
    assert zone.current is not None
    assert zone.current.measured_temperature == 20.1


def test_non_dict_group_value_is_retained_without_observation(
    model: RinnaiStatusModel,
) -> None:
    snapshot = apply_payloads(model, [{"SYST": "unexpected"}])
    assert snapshot.raw_groups["SYST"] == "unexpected"
    assert snapshot.operating_mode is None
    assert snapshot.fault.active is None
    assert list(snapshot.zones) == []
