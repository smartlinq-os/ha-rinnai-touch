"""Offline status model for the Rinnai Touch protocol.

Consumes validated :class:`~.protocol.ParsedFrame` payloads and produces
immutable typed snapshots for the future client, coordinator, diagnostics,
and entity layers. Pure Python: no I/O, no Home Assistant, deterministic.

The model keeps three strictly separated layers (AGENT_SCOPE.md "Status
Merge and Retention Semantics", docs/protocol_assumptions.md):

Latest raw top-level groups
    Each received top-level group (``SYST``, ``HGOM``, ``CGOM``, ``ECOM``,
    or any unknown future group) *replaces* the previously stored copy of
    that group exactly. Nested fields are never deep-merged: a later partial
    ``SYST`` drops earlier ``SYST`` subgroups from the raw layer. Unknown
    groups and unknown nested fields are retained structurally as decoded
    JSON data, without dropping or interpreting them; only
    :attr:`~.protocol.ParsedFrame.raw_frame` is byte-exact wire text.

Cumulative observations
    Capabilities (heater/cooler/evaporative availability, multi-setpoint,
    temperature unit) and zone facts (observed letters, installed flags,
    display names) are accumulated conservatively across frames and never
    disappear because a later frame omits a group or field, shows ``N``
    after an earlier ``Y``, or because the operating mode changed. Removal
    or reconfiguration policy belongs to a later approved milestone.
    Zone observation policy: a zone letter becomes *observed* when any
    evidence for it appears — an installed flag (any value), a configured
    name, or a sensed/option subgroup — but *installed* is latched only by
    an explicit ``Z?IS == "Y"``. A zone seen only via a sensed group is
    therefore observed-but-not-installed rather than manufactured.

Current typed state
    Operating mode, controller state, and the fault record are read from
    the *latest raw* ``SYST`` group only; after a partial ``SYST`` replaces
    a fuller one, fields it no longer carries become unknown (``None``)
    rather than being claimed from stale data. The active mode group name
    is derived from ``OSS.MD`` (``H``/``C``/``E`` map to ``HGOM``/``CGOM``/
    ``ECOM``; ``R``, ``N``, and unknown codes map to no active group), and
    per-zone current status is built exclusively from that active group —
    never from a retained stale mode group.

Immutability strategy
    ``apply()`` deep-copies incoming group data into internal storage (the
    frame is never mutated or aliased) and every snapshot deep-copies the
    raw layer again, wrapping top-level mappings in ``MappingProxyType``.
    Mutating a snapshot's nested dictionaries therefore only alters the
    caller's private copy; model state and future snapshots are unaffected,
    and all value objects are frozen dataclasses.

Value handling
    ``MT`` is tenths of a degree: ``"223"`` or ``223`` become ``22.3``;
    the ``999`` no-reading sentinel, missing values, and anything
    non-numeric become ``None`` — never zero or a fabricated reading.
    Evaporative setpoints are *not* temperatures; all zone option fields
    (``UE``/``OP``/``SP``/``AO``) are exposed as raw observational strings
    until real hardware validation. Unknown mode, state, fault, or zone
    values survive safely without raising.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from .const import MT_NO_READING, ZONE_LETTERS
from .protocol import ParsedFrame

_SYSTEM_GROUP: Final = "SYST"
_MODE_GROUP_BY_MODE: Final = {"H": "HGOM", "C": "CGOM", "E": "ECOM"}
_MODE_GROUPS: Final = frozenset(_MODE_GROUP_BY_MODE.values())
_COMMON_ZONE: Final = "U"
_MT_SENTINEL_TENTHS: Final = int(MT_NO_READING)


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Cumulative capability observations (latched, never inferred).

    Each ``*_observed`` flag records that the corresponding ``SYST.AVM``
    or ``SYST.CFG`` field has been seen as ``Y`` at least once on this
    connection's stream; an omission or later ``N`` does not clear it.
    ``temperature_unit`` is the most recently observed non-empty ``CFG.TU``.
    """

    heater_observed: bool = False
    cooler_observed: bool = False
    evaporative_observed: bool = False
    multi_setpoint_observed: bool = False
    temperature_unit: str | None = None


@dataclass(frozen=True, slots=True)
class ZoneStatus:
    """Current observational data for one zone from the active mode group.

    ``measured_temperature`` is degrees (converted from tenths) or ``None``
    when absent, invalid, or the ``999`` no-reading sentinel. Option fields
    are raw protocol strings — including setpoints, which on evaporative
    systems are comfort levels rather than temperatures and therefore stay
    untyped until validated.
    """

    measured_temperature: float | None = None
    raw_measured_temperature: str | None = None
    auto_enabled: bool | None = None
    user_enabled_raw: str | None = None
    control_mode_raw: str | None = None
    setpoint_raw: str | None = None
    schedule_override_raw: str | None = None


@dataclass(frozen=True, slots=True)
class ZoneObservation:
    """Everything known about one protocol zone letter.

    ``installed_observed`` is cumulative (latched by ``Z?IS == "Y"`` in any
    mode group). ``current`` is present only when the currently active mode
    group carries sensed or option data for this zone; it is never taken
    from a stale, non-active mode group.
    """

    letter: str
    name: str
    installed_observed: bool
    current: ZoneStatus | None


@dataclass(frozen=True, slots=True)
class FaultRecord:
    """Conservative view of the latest raw ``SYST.FLT`` subgroup.

    ``active`` is ``True``/``False`` for ``Y``/``N`` and ``None`` when the
    flag is absent or unrecognised. The optional fields are preserved as
    raw strings without interpretation; firmware-variant keys beyond these
    remain available in the snapshot's raw groups.
    """

    active: bool | None = None
    appliance_raw: str | None = None
    unit_raw: str | None = None
    severity_raw: str | None = None
    code_raw: str | None = None


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """Immutable view of the model after one applied frame.

    ``raw_groups`` is a read-only mapping over a defensive deep copy of the
    latest top-level groups; mutating its nested structures affects only
    the caller's copy. ``zones`` maps observed zone letters (in ``U``,
    ``A``-``D`` order) to frozen observations. ``active_mode_group`` names
    the group implied by ``operating_mode`` even if that group has not been
    received yet; per-zone ``current`` data additionally requires the group
    to be present.
    """

    sequence: int
    raw_groups: Mapping[str, Any]
    capabilities: Capabilities
    zones: Mapping[str, ZoneObservation]
    operating_mode: str | None
    controller_state: str | None
    active_mode_group: str | None
    fault: FaultRecord


def _yn(value: object) -> bool | None:
    """Map protocol Y/N flags to booleans; anything else is unknown."""
    if value == "Y":
        return True
    if value == "N":
        return False
    return None


def _raw_str(value: object) -> str | None:
    """Return string values as-is; non-strings are treated as absent."""
    return value if isinstance(value, str) else None


def _subgroup(group: object, key: str) -> dict[str, Any] | None:
    """Return ``group[key]`` when both levels are dicts, else ``None``."""
    if isinstance(group, dict):
        value = group.get(key)
        if isinstance(value, dict):
            return value
    return None


def _parse_measured_temperature(raw: object) -> float | None:
    """Convert an ``MT`` tenths value to degrees, or ``None``.

    Accepts integers and numeric strings. The ``999`` sentinel, booleans,
    empty/whitespace strings, and non-numeric input all yield ``None``.
    """
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        tenths = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            tenths = int(text)
        except ValueError:
            return None
    else:
        return None
    if tenths == _MT_SENTINEL_TENTHS:
        return None
    return tenths / 10.0


def _fallback_zone_name(letter: str) -> str:
    """Default display name when the controller has not supplied one."""
    return "Common" if letter == _COMMON_ZONE else f"Zone {letter}"


def _build_fault(flt: dict[str, Any] | None) -> FaultRecord:
    if flt is None:
        return FaultRecord()
    return FaultRecord(
        active=_yn(flt.get("AV")),
        appliance_raw=_raw_str(flt.get("GP")),
        unit_raw=_raw_str(flt.get("UT")),
        severity_raw=_raw_str(flt.get("TP")),
        code_raw=_raw_str(flt.get("CD")),
    )


def _build_zone_status(
    active_group: dict[str, Any], letter: str
) -> ZoneStatus | None:
    """Build current zone data from the active mode group, if any exists.

    Returns ``None`` when the group carries neither a sensed (``Z?S``) nor
    an option (``Z?O``) subgroup for the zone, so a ``ZoneStatus`` object
    always reflects actual current-mode data. ``ZUO`` is read like any
    other option subgroup if present but is never assumed to exist.
    """
    sensed = _subgroup(active_group, f"Z{letter}S")
    options = _subgroup(active_group, f"Z{letter}O")
    if sensed is None and options is None:
        return None
    mt_raw: object = sensed.get("MT") if sensed else None
    raw_mt_text = (
        str(mt_raw)
        if isinstance(mt_raw, str | int) and not isinstance(mt_raw, bool)
        else None
    )
    return ZoneStatus(
        measured_temperature=_parse_measured_temperature(mt_raw),
        raw_measured_temperature=raw_mt_text,
        auto_enabled=_yn(sensed.get("AE")) if sensed else None,
        user_enabled_raw=_raw_str(options.get("UE")) if options else None,
        control_mode_raw=_raw_str(options.get("OP")) if options else None,
        setpoint_raw=_raw_str(options.get("SP")) if options else None,
        schedule_override_raw=_raw_str(options.get("AO")) if options else None,
    )


class RinnaiStatusModel:
    """Mutable model: apply parsed frames, receive immutable snapshots.

    The model performs no I/O and holds no sockets or timers. It never
    mutates the frames it is given, exposes no command or keepalive
    functionality, and defers deduplication, availability, and outgoing
    sequence arithmetic to later approved layers.
    """

    def __init__(self) -> None:
        self._sequence = 0
        self._groups: dict[str, Any] = {}
        self._heater_observed = False
        self._cooler_observed = False
        self._evaporative_observed = False
        self._multi_setpoint_observed = False
        self._temperature_unit: str | None = None
        self._zones_observed: set[str] = set()
        self._zones_installed: set[str] = set()
        self._zone_names: dict[str, str] = {}

    def apply(self, frame: ParsedFrame) -> StatusSnapshot:
        """Fold one validated frame into the model and snapshot the result.

        An empty payload updates only the latest sequence: raw groups,
        observations, and derived state are untouched and no state change
        is inferred.
        """
        self._sequence = frame.sequence
        for item in frame.payload:
            # The parser guarantees each item is a single-key object.
            for group_key, group_value in item.items():
                # Deep-copy so neither the frame nor callers share storage
                # with the model, and replacement is exact (no deep merge).
                self._groups[group_key] = copy.deepcopy(group_value)
                self._observe_group(group_key, group_value)
        return self._build_snapshot()

    # --- cumulative observation -------------------------------------------

    def _observe_group(self, group_key: str, group_value: object) -> None:
        if not isinstance(group_value, dict):
            return  # retained raw-only; nothing observable
        if group_key == _SYSTEM_GROUP:
            self._observe_system(group_value)
        elif group_key in _MODE_GROUPS:
            self._observe_mode_group(group_value)

    def _observe_system(self, system: dict[str, Any]) -> None:
        cfg = _subgroup(system, "CFG")
        if cfg is not None:
            if _yn(cfg.get("MTSP")) is True:
                self._multi_setpoint_observed = True
            unit = _raw_str(cfg.get("TU"))
            if unit is not None and unit.strip():
                self._temperature_unit = unit.strip()
            for letter in ZONE_LETTERS:
                name = _raw_str(cfg.get(f"Z{letter}"))
                if name is not None and name.strip():
                    # Most recent non-empty name wins; empty or whitespace
                    # names never erase a previously known name.
                    self._zone_names[letter] = name.strip()
                    self._zones_observed.add(letter)
        avm = _subgroup(system, "AVM")
        if avm is not None:
            if _yn(avm.get("HG")) is True:
                self._heater_observed = True
            if _yn(avm.get("CG")) is True:
                self._cooler_observed = True
            if _yn(avm.get("EC")) is True:
                self._evaporative_observed = True

    def _observe_mode_group(self, mode_group: dict[str, Any]) -> None:
        cfg = _subgroup(mode_group, "CFG")
        for letter in ZONE_LETTERS:
            if cfg is not None and f"Z{letter}IS" in cfg:
                # Any installed flag mentions the zone; only "Y" latches
                # installation, and a later "N" never unlatches it.
                self._zones_observed.add(letter)
                if _yn(cfg.get(f"Z{letter}IS")) is True:
                    self._zones_installed.add(letter)
            if f"Z{letter}S" in mode_group or f"Z{letter}O" in mode_group:
                self._zones_observed.add(letter)

    # --- snapshot construction --------------------------------------------

    def _build_snapshot(self) -> StatusSnapshot:
        system = self._groups.get(_SYSTEM_GROUP)
        oss = _subgroup(system, "OSS")
        mode = _raw_str(oss.get("MD")) if oss else None
        controller_state = _raw_str(oss.get("ST")) if oss else None
        active_name = _MODE_GROUP_BY_MODE.get(mode) if mode else None
        active_group = (
            self._groups.get(active_name) if active_name is not None else None
        )
        zones: dict[str, ZoneObservation] = {}
        for letter in ZONE_LETTERS:  # stable U, A-D presentation order
            if letter not in self._zones_observed:
                continue
            current = (
                _build_zone_status(active_group, letter)
                if isinstance(active_group, dict)
                else None
            )
            zones[letter] = ZoneObservation(
                letter=letter,
                name=self._zone_names.get(letter, _fallback_zone_name(letter)),
                installed_observed=letter in self._zones_installed,
                current=current,
            )
        return StatusSnapshot(
            sequence=self._sequence,
            raw_groups=MappingProxyType(copy.deepcopy(self._groups)),
            capabilities=Capabilities(
                heater_observed=self._heater_observed,
                cooler_observed=self._cooler_observed,
                evaporative_observed=self._evaporative_observed,
                multi_setpoint_observed=self._multi_setpoint_observed,
                temperature_unit=self._temperature_unit,
            ),
            zones=MappingProxyType(zones),
            operating_mode=mode,
            controller_state=controller_state,
            active_mode_group=active_name,
            fault=_build_fault(_subgroup(system, "FLT")),
        )
