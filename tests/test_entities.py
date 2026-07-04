"""Offline tests for the read-only Rinnai Touch entity layer.

Skipped as a whole without the ``ha-test`` dependency group. This module is
deliberately NOT in the loopback opt-in list (see
tests/test_project_structure.py): pytest-homeassistant-custom-component
blocks socket creation for every test here, so the entity layer is proven
passive by construction — no test in this file can open any socket, and the
first test asserts exactly that.

The harness monkeypatches the ``RinnaiTouchCoordinator`` name bound in the
package ``__init__`` so that real config-entry setup builds the coordinator
with the shared fake client and fake clocks from tests/conftest.py. Tests
then drive the coordinator through its client-callback handlers exactly as
test_coordinator.py does — synchronously, as the real client's dispatcher
would — and observe entity behaviour through the normal Home Assistant
state machine and registries.
"""

from __future__ import annotations

import json
import logging
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Final

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="ha-test dependency group is not installed",
)

from conftest import FakeMonotonic, FakeRinnaiClient, FakeWallClock
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.rinnai_touch as rinnai_touch_init
from custom_components.rinnai_touch.client import (
    ConnectionEvent,
    ConnectionState,
)
from custom_components.rinnai_touch.const import (
    CONF_HOST,
    CONF_PORT,
    DEFAULT_TCP_PORT,
    DOMAIN,
    STALE_STATUS_THRESHOLD_SECONDS,
)
from custom_components.rinnai_touch.coordinator import RinnaiTouchCoordinator
from custom_components.rinnai_touch.models import (
    RinnaiStatusModel,
    StatusSnapshot,
)
from custom_components.rinnai_touch.protocol import RinnaiFrameParser

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

# RFC 2606 reserved name: can never resolve, and the fake client never
# connects anyway. Deliberately not an IP literal — this module does no
# networking of any kind.
TEST_HOST: Final = "module.invalid"

SENSOR: Final = "sensor"
BINARY_SENSOR: Final = "binary_sensor"

# The approved inventory: (platform, fixed unique suffix).
HEALTH_ENTITIES: Final = (
    (BINARY_SENSOR, "connectivity"),
    (SENSOR, "data_freshness"),
    (SENSOR, "last_valid_status"),
)
SNAPSHOT_ENTITIES: Final = (
    (SENSOR, "operating_mode"),
    (SENSOR, "controller_state"),
    (BINARY_SENSOR, "fault_active"),
)
ALL_ENTITIES: Final = HEALTH_ENTITIES + SNAPSHOT_ENTITIES

# Mirrors the synthetic fixture's SYST shape: mode/state codes plus an
# inactive fault flag.
FULL_STATUS_PAYLOAD: Final[list[dict[str, object]]] = [
    {"SYST": {"OSS": {"MD": "H", "ST": "N"}, "FLT": {"AV": "N"}}}
]


def build_snapshot(
    payload: list[dict[str, object]], sequence: int = 1
) -> StatusSnapshot:
    """Run one real wire frame through the pure layers into a snapshot."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    frames = RinnaiFrameParser().feed(f"N{sequence:06d}{body}".encode())
    assert len(frames) == 1
    return RinnaiStatusModel().apply(frames[0])


@dataclass
class EntityHarness:
    """One configured entry wired to fake clocks and a fake client."""

    hass: HomeAssistant
    entry: MockConfigEntry
    coordinator: RinnaiTouchCoordinator
    clients: list[FakeRinnaiClient]
    monotonic: FakeMonotonic
    wall: FakeWallClock

    @property
    def client(self) -> FakeRinnaiClient:
        return self.clients[-1]

    def entity_id(self, platform: str, suffix: str) -> str:
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            platform, DOMAIN, f"{self.entry.entry_id}_{suffix}"
        )
        assert entity_id is not None, (platform, suffix)
        return entity_id

    def state_of(self, platform: str, suffix: str) -> State:
        state = self.hass.states.get(self.entity_id(platform, suffix))
        assert state is not None, (platform, suffix)
        return state

    async def push_snapshot(
        self, payload: list[dict[str, object]], sequence: int = 1
    ) -> StatusSnapshot:
        """Deliver one snapshot exactly as the client dispatcher would."""
        snapshot = build_snapshot(payload, sequence)
        self.coordinator._handle_snapshot(snapshot)
        await self.hass.async_block_till_done()
        return snapshot

    async def push_connection_event(
        self, state: ConnectionState, error: str | None = None
    ) -> None:
        self.coordinator._handle_connection_event(ConnectionEvent(state, error))
        await self.hass.async_block_till_done()

    async def go_stale(self) -> None:
        """Advance past the threshold and deliver the stale announcement."""
        self.monotonic.advance(STALE_STATUS_THRESHOLD_SECONDS + 1)
        self.coordinator._async_check_stale()
        await self.hass.async_block_till_done()


@pytest.fixture
async def harness(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[EntityHarness]:
    """Set up one real config entry over fully faked clocks and client."""
    monotonic = FakeMonotonic()
    wall = FakeWallClock()
    clients: list[FakeRinnaiClient] = []

    def _client_factory(host: str, port: int, **kwargs: Any) -> FakeRinnaiClient:
        client = FakeRinnaiClient(host, port, **kwargs)
        clients.append(client)
        return client

    real_coordinator = rinnai_touch_init.RinnaiTouchCoordinator

    def _coordinator_with_fakes(
        hass_arg: HomeAssistant, **kwargs: Any
    ) -> RinnaiTouchCoordinator:
        return real_coordinator(
            hass_arg,
            client_factory=_client_factory,
            wall_clock=wall,
            monotonic_clock=monotonic,
            **kwargs,
        )

    monkeypatch.setattr(
        rinnai_touch_init, "RinnaiTouchCoordinator", _coordinator_with_fakes
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: TEST_HOST, CONF_PORT: DEFAULT_TCP_PORT},
        title=f"Rinnai Touch ({TEST_HOST})",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    fixture = EntityHarness(
        hass, entry, entry.runtime_data, clients, monotonic, wall
    )
    yield fixture
    if entry.state is ConfigEntryState.LOADED:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


# --- this module runs fully socket-blocked -------------------------------------


def test_module_cannot_create_sockets() -> None:
    """Not loopback-opted-in: the socket guard is active in this module.

    This is the structural passivity guarantee for the entity layer.
    pytest-homeassistant-custom-component installs pytest-socket's guard
    before every test and *fails any test that even attempts* a blocked
    socket (its teardown asserts no SocketBlockedError was ever raised),
    so this test verifies the guard is installed instead of tripping it.
    """
    assert socket.socket.__module__ == "pytest_socket"
    assert "GuardedSocket" in socket.socket.__qualname__


# --- inventory and identity -----------------------------------------------------


async def test_exact_inventory_unique_ids_and_device(
    harness: EntityHarness,
) -> None:
    registry = er.async_get(harness.hass)
    entries = er.async_entries_for_config_entry(registry, harness.entry.entry_id)
    assert len(entries) == len(ALL_ENTITIES) == 6
    expected_unique_ids = {
        f"{harness.entry.entry_id}_{suffix}" for _, suffix in ALL_ENTITIES
    }
    assert {entry.unique_id for entry in entries} == expected_unique_ids
    for registry_entry in entries:
        assert registry_entry.entity_category is EntityCategory.DIAGNOSTIC
        assert registry_entry.disabled_by is None  # enabled by default
    # Exactly one module device, keyed on the config-entry ID alone.
    device_registry = dr.async_get(harness.hass)
    devices = dr.async_entries_for_config_entry(
        device_registry, harness.entry.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, harness.entry.entry_id)}
    assert device.name == harness.entry.title
    assert device.manufacturer == "Rinnai"
    assert device.model is None  # not evidenced; deliberately unset
    for registry_entry in entries:
        assert registry_entry.device_id == device.id


async def test_names_device_classes_and_options(harness: EntityHarness) -> None:
    assert (
        harness.state_of(BINARY_SENSOR, "connectivity").attributes["device_class"]
        == "connectivity"
    )
    freshness = harness.state_of(SENSOR, "data_freshness")
    assert freshness.attributes["device_class"] == "enum"
    assert freshness.attributes["options"] == ["no_data", "fresh", "stale"]
    assert (
        harness.state_of(SENSOR, "last_valid_status").attributes["device_class"]
        == "timestamp"
    )
    assert (
        harness.state_of(BINARY_SENSOR, "fault_active").attributes["device_class"]
        == "problem"
    )
    # Raw protocol code sensors carry no device class and no options.
    for suffix in ("operating_mode", "controller_state"):
        attributes = harness.state_of(SENSOR, suffix).attributes
        assert "device_class" not in attributes
        assert "options" not in attributes
    # Names come from the entity translations; the device name prefixes them.
    title = harness.entry.title
    expected_names = {
        (BINARY_SENSOR, "connectivity"): "Connectivity",
        (SENSOR, "data_freshness"): "Data freshness",
        (SENSOR, "last_valid_status"): "Last valid status",
        (SENSOR, "operating_mode"): "Operating mode",
        (SENSOR, "controller_state"): "Controller state",
        (BINARY_SENSOR, "fault_active"): "Fault active",
    }
    for (platform, suffix), name in expected_names.items():
        state = harness.state_of(platform, suffix)
        assert state.attributes["friendly_name"] == f"{title} {name}"


# --- health presentation with no data --------------------------------------------


async def test_no_data_health_presentation(harness: EntityHarness) -> None:
    # Health entities are available and meaningful before any frame:
    assert harness.state_of(BINARY_SENSOR, "connectivity").state == STATE_OFF
    assert harness.state_of(SENSOR, "data_freshness").state == "no_data"
    assert harness.state_of(SENSOR, "last_valid_status").state == STATE_UNKNOWN
    # ... while snapshot entities are unavailable, not unknown or fabricated.
    for platform, suffix in SNAPSHOT_ENTITIES:
        assert harness.state_of(platform, suffix).state == STATE_UNAVAILABLE


async def test_connectivity_is_distinct_from_freshness(
    harness: EntityHarness,
) -> None:
    await harness.push_connection_event(ConnectionState.CONNECTING)
    assert harness.state_of(BINARY_SENSOR, "connectivity").state == STATE_OFF
    await harness.push_connection_event(ConnectionState.CONNECTED)
    # A connected socket changes connectivity only: still no data at all.
    assert harness.state_of(BINARY_SENSOR, "connectivity").state == STATE_ON
    assert harness.state_of(SENSOR, "data_freshness").state == "no_data"
    for platform, suffix in SNAPSHOT_ENTITIES:
        assert harness.state_of(platform, suffix).state == STATE_UNAVAILABLE
    await harness.push_connection_event(
        ConnectionState.CONNECTION_FAILED, "connection closed by remote end"
    )
    assert harness.state_of(BINARY_SENSOR, "connectivity").state == STATE_OFF
    assert harness.state_of(SENSOR, "data_freshness").state == "no_data"


# --- snapshot arrival, staleness, and recovery ------------------------------------


async def test_first_valid_snapshot_populates_entities(
    harness: EntityHarness,
) -> None:
    await harness.push_connection_event(ConnectionState.CONNECTED)
    await harness.push_snapshot(FULL_STATUS_PAYLOAD)
    assert harness.state_of(BINARY_SENSOR, "connectivity").state == STATE_ON
    assert harness.state_of(SENSOR, "data_freshness").state == "fresh"
    assert harness.state_of(SENSOR, "last_valid_status").state == (
        harness.wall.now.isoformat()
    )
    assert harness.state_of(SENSOR, "operating_mode").state == "H"
    assert harness.state_of(SENSOR, "controller_state").state == "N"
    assert harness.state_of(BINARY_SENSOR, "fault_active").state == STATE_OFF


async def test_stale_transition(harness: EntityHarness) -> None:
    await harness.push_connection_event(ConnectionState.CONNECTED)
    await harness.push_snapshot(FULL_STATUS_PAYLOAD)
    stamped = harness.state_of(SENSOR, "last_valid_status").state
    await harness.go_stale()
    # Freshness reports STALE and stays available...
    assert harness.state_of(SENSOR, "data_freshness").state == "stale"
    # ...snapshot-derived entities go unavailable...
    for platform, suffix in SNAPSHOT_ENTITIES:
        assert harness.state_of(platform, suffix).state == STATE_UNAVAILABLE
    # ...and the other health entities are untouched: the socket is still
    # connected and the historical timestamp remains valid and available.
    assert harness.state_of(BINARY_SENSOR, "connectivity").state == STATE_ON
    assert harness.state_of(SENSOR, "last_valid_status").state == stamped


async def test_recovery_to_fresh(harness: EntityHarness) -> None:
    await harness.push_snapshot(FULL_STATUS_PAYLOAD)
    await harness.go_stale()
    harness.wall.advance(300)
    await harness.push_snapshot(FULL_STATUS_PAYLOAD, sequence=2)
    assert harness.state_of(SENSOR, "data_freshness").state == "fresh"
    assert harness.state_of(SENSOR, "operating_mode").state == "H"
    assert harness.state_of(SENSOR, "controller_state").state == "N"
    assert harness.state_of(BINARY_SENSOR, "fault_active").state == STATE_OFF
    assert harness.state_of(SENSOR, "last_valid_status").state == (
        harness.wall.now.isoformat()
    )


# --- fresh snapshots with missing or unrecognised fields ---------------------------


async def test_missing_fields_read_unknown_not_unavailable(
    harness: EntityHarness,
) -> None:
    # A fresh snapshot whose SYST carries neither OSS nor FLT: the entities
    # stay available (data is fresh) but report unknown — never a value.
    await harness.push_snapshot([{"SYST": {"CFG": {"TU": "C"}}}])
    assert harness.state_of(SENSOR, "data_freshness").state == "fresh"
    for platform, suffix in SNAPSHOT_ENTITIES:
        assert harness.state_of(platform, suffix).state == STATE_UNKNOWN


async def test_unknown_raw_codes_pass_through_unchanged(
    harness: EntityHarness,
) -> None:
    # Unrecognised protocol codes must survive verbatim: no enum contract,
    # no interpretation, no error.
    await harness.push_snapshot([{"SYST": {"OSS": {"MD": "X", "ST": "Q"}}}])
    assert harness.state_of(SENSOR, "operating_mode").state == "X"
    assert harness.state_of(SENSOR, "controller_state").state == "Q"


async def test_fault_active_reflects_the_parsed_flag(
    harness: EntityHarness,
) -> None:
    await harness.push_snapshot([{"SYST": {"FLT": {"AV": "Y"}}}])
    assert harness.state_of(BINARY_SENSOR, "fault_active").state == STATE_ON
    await harness.push_snapshot([{"SYST": {"FLT": {"AV": "N"}}}], sequence=2)
    assert harness.state_of(BINARY_SENSOR, "fault_active").state == STATE_OFF


# --- connection loss inside the fresh window ---------------------------------------


async def test_disconnect_during_fresh_window_keeps_snapshot_entities(
    harness: EntityHarness,
) -> None:
    await harness.push_connection_event(ConnectionState.CONNECTED)
    await harness.push_snapshot(FULL_STATUS_PAYLOAD)
    harness.monotonic.advance(60)
    await harness.push_connection_event(
        ConnectionState.CONNECTION_FAILED, "connection closed by remote end"
    )
    await harness.push_connection_event(ConnectionState.RECONNECTING)
    # Connectivity reports the dead socket; 60-second-old data is still
    # fresh, so snapshot entities remain available with their values.
    assert harness.state_of(BINARY_SENSOR, "connectivity").state == STATE_OFF
    assert harness.state_of(SENSOR, "data_freshness").state == "fresh"
    assert harness.state_of(SENSOR, "operating_mode").state == "H"
    assert harness.state_of(SENSOR, "controller_state").state == "N"
    assert harness.state_of(BINARY_SENSOR, "fault_active").state == STATE_OFF


# --- manual updates cause no side effects ------------------------------------------


async def test_manual_update_entity_causes_no_side_effects(
    harness: EntityHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert await async_setup_component(harness.hass, "homeassistant", {})
    await harness.push_connection_event(ConnectionState.CONNECTED)
    await harness.push_snapshot(FULL_STATUS_PAYLOAD)
    refresh_calls: list[int] = []

    async def _spy_refresh() -> None:
        refresh_calls.append(1)

    # If the no-op async_update safeguard regressed, CoordinatorEntity's
    # default would reach async_request_refresh and this spy would record.
    monkeypatch.setattr(
        harness.coordinator, "async_request_refresh", _spy_refresh
    )
    data_before = harness.coordinator.data
    start_calls = harness.client.start_calls
    stop_calls = harness.client.stop_calls
    states_before = {
        (platform, suffix): harness.state_of(platform, suffix).state
        for platform, suffix in ALL_ENTITIES
    }
    caplog.clear()
    await harness.hass.services.async_call(
        "homeassistant",
        "update_entity",
        {
            "entity_id": [
                harness.entity_id(platform, suffix)
                for platform, suffix in ALL_ENTITIES
            ]
        },
        blocking=True,
    )
    await harness.hass.async_block_till_done()
    assert refresh_calls == []  # no coordinator refresh machinery
    assert harness.client.start_calls == start_calls  # no client activity
    assert harness.client.stop_calls == stop_calls
    assert harness.coordinator.data is data_before  # nothing fabricated
    assert harness.coordinator.last_update_success is True
    assert harness.coordinator.last_exception is None
    for (platform, suffix), state in states_before.items():
        assert harness.state_of(platform, suffix).state == state
    errors = [
        record for record in caplog.records if record.levelno >= logging.ERROR
    ]
    assert errors == []


# --- unload and reload ---------------------------------------------------------------


async def test_unload_and_reload_are_stable(harness: EntityHarness) -> None:
    hass = harness.hass
    entry = harness.entry
    ids_before = {
        (platform, suffix): harness.entity_id(platform, suffix)
        for platform, suffix in ALL_ENTITIES
    }
    first_client = harness.client
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    # Graceful shutdown: unload stops the client. Home Assistant's
    # DataUpdateCoordinator also registers its own shutdown on entry
    # unload, so the repeat-safe contract may legitimately stop it twice.
    assert first_client.stop_calls >= 1
    # Registered entities are not deleted on unload: the state machine
    # keeps restored, unavailable placeholders for them.
    for entity_id in ids_before.values():
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == STATE_UNAVAILABLE
        assert state.attributes.get("restored") is True
    # Setting up again (the reload path) must reuse every entity identity:
    # unique IDs are entry-ID based, so registry entity IDs cannot change.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert len(harness.clients) == 2  # a fresh client for the new runtime
    harness.coordinator = entry.runtime_data
    for (platform, suffix), entity_id in ids_before.items():
        assert harness.entity_id(platform, suffix) == entity_id
    # The new runtime starts with no data: health entities report exactly
    # that while snapshot entities are unavailable again.
    assert harness.state_of(SENSOR, "data_freshness").state == "no_data"
    assert harness.state_of(SENSOR, "last_valid_status").state == STATE_UNKNOWN
    for platform, suffix in SNAPSHOT_ENTITIES:
        assert harness.state_of(platform, suffix).state == STATE_UNAVAILABLE
