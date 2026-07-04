"""Offline tests for the Rinnai Touch config-entry lifecycle.

Skipped as a whole without the ``ha-test`` dependency group. All networking
is in-process 127.0.0.1 loopback. These tests prove the approved lifecycle:
setup builds and starts the passive coordinator and succeeds even when the
module is unreachable (the client owns retry/backoff — no
ConfigEntryNotReady), unload shuts the coordinator down, the Home Assistant
stop event closes the connection gracefully, and repeated shutdown paths
stay harmless.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="ha-test dependency group is not installed",
)

from conftest import LoopbackServer
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rinnai_touch.const import CONF_HOST, CONF_PORT, DOMAIN
from custom_components.rinnai_touch.coordinator import (
    Freshness,
    RinnaiTouchCoordinator,
)

# In-process 127.0.0.1 servers only; opt-in fixture defined in tests/conftest.py.
pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "loopback_socket_enabled"
)

LOOPBACK_HOST = "127.0.0.1"


def encode_frame(sequence: int, payload: list[dict[str, object]]) -> bytes:
    """Build one wire frame: N + six-digit sequence + JSON array."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"N{sequence:06d}{body}".encode()


STATUS_FRAME = encode_frame(1, [{"SYST": {"OSS": {"MD": "H", "ST": "N"}}}])


async def wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    """Poll a condition with a hard timeout; keeps tests deterministic."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.001)


async def _setup_entry(
    hass: HomeAssistant, host: str, port: int
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_PORT: port},
        title=f"Rinnai Touch ({host})",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_starts_coordinator_and_receives_status(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    entry = await _setup_entry(hass, LOOPBACK_HOST, loopback_server.port)
    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data
    assert isinstance(coordinator, RinnaiTouchCoordinator)
    await loopback_server.wait_for_connection()
    await loopback_server.send(STATUS_FRAME)
    await wait_until(lambda: coordinator.data is not None)
    assert coordinator.data.operating_mode == "H"
    assert coordinator.freshness is Freshness.FRESH
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await loopback_server.wait_all_closed()
    assert bytes(loopback_server.received) == b""  # end-to-end passive


async def test_setup_succeeds_when_module_unreachable(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    refused_port = loopback_server.port
    await loopback_server.stop()  # connects to this port are now refused
    # Approved D1: no ConfigEntryNotReady — the entry loads and the passive
    # client owns reconnect/backoff in the background.
    entry = await _setup_entry(hass, LOOPBACK_HOST, refused_port)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.data is None
    assert entry.runtime_data.freshness is Freshness.NO_DATA
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_unload_shuts_down_client_and_drops_runtime_data(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    entry = await _setup_entry(hass, LOOPBACK_HOST, loopback_server.port)
    await loopback_server.wait_for_connection()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    await loopback_server.wait_all_closed()
    for _ in range(20):  # no reconnect after unload
        await asyncio.sleep(0.001)
    assert loopback_server.connection_count == 1
    assert not hasattr(entry, "runtime_data")  # removed with the entry


async def test_ha_stop_event_closes_connection_gracefully(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    entry = await _setup_entry(hass, LOOPBACK_HOST, loopback_server.port)
    await loopback_server.wait_for_connection()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    await loopback_server.wait_all_closed()
    for _ in range(20):  # shut down, not reconnecting
        await asyncio.sleep(0.001)
    assert loopback_server.connection_count == 1
    # Unloading afterwards repeats coordinator shutdown; it must stay
    # harmless (mandatory rule 5).
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_reload_creates_a_fresh_connection(
    hass: HomeAssistant, loopback_server: LoopbackServer
) -> None:
    entry = await _setup_entry(hass, LOOPBACK_HOST, loopback_server.port)
    await loopback_server.wait_for_connection()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await loopback_server.wait_for_connection(count=2)
    assert loopback_server.connection_count == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
