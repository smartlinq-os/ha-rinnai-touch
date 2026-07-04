"""Rinnai Touch: local-only, passive Home Assistant integration.

Config-entry lifecycle plus the read-only entity layer: setup builds and
starts the passive push :class:`~.coordinator.RinnaiTouchCoordinator`, then
forwards the sensor and binary_sensor platforms; unload unloads those
platforms and shuts the coordinator down. No control platforms, services,
diagnostics, or options flow exist — those follow in later approved
milestones, and no write path exists anywhere.

Setup never raises ``ConfigEntryNotReady``: the passive client owns all
reconnect/backoff behaviour (approved decision D1), so an entry loads even
while the module is temporarily unreachable and availability is expressed
through the coordinator's freshness model instead. Per AGENT_SCOPE.md
safety rule 8, the TCP connection is closed gracefully on Home Assistant
stop (listener registered through ``entry.async_on_unload``), on entry
unload, and on reload (unload + setup); coordinator shutdown is safe to
repeat, so overlapping paths stay harmless.
"""

from __future__ import annotations

from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from .const import CONF_HOST, CONF_PORT, DEFAULT_TCP_PORT
from .coordinator import RinnaiTouchCoordinator

PLATFORMS: Final = [Platform.BINARY_SENSOR, Platform.SENSOR]

type RinnaiTouchConfigEntry = ConfigEntry[RinnaiTouchCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: RinnaiTouchConfigEntry
) -> bool:
    """Start the passive coordinator and the read-only entity platforms."""
    coordinator = RinnaiTouchCoordinator(
        hass,
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_TCP_PORT),
        config_entry=entry,
    )
    entry.runtime_data = coordinator
    await coordinator.async_start()

    async def _async_shutdown_on_ha_stop(_event: Event) -> None:
        # Graceful socket close on Home Assistant stop (AGENT_SCOPE rule 8).
        # The async listener runs as a task on the HA event loop; repeating
        # shutdown later (unload) is harmless by the coordinator's contract.
        await coordinator.async_shutdown()

    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, _async_shutdown_on_ha_stop
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RinnaiTouchConfigEntry
) -> bool:
    """Unload the entity platforms, then shut the coordinator down.

    Runtime data is dropped with the entry. The coordinator is shut down
    only on a successful platform unload, so a failed unload leaves the
    entry consistently loaded rather than half-torn-down.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
