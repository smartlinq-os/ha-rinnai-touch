"""Rinnai Touch: local-only, passive Home Assistant integration.

Config-entry lifecycle only at this milestone: setup builds and starts the
passive push :class:`~.coordinator.RinnaiTouchCoordinator`; unload shuts it
down. No entity platforms, diagnostics, options flow, or write paths exist
yet — those follow in later approved milestones.

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

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant

from .const import CONF_HOST, CONF_PORT, DEFAULT_TCP_PORT
from .coordinator import RinnaiTouchCoordinator

type RinnaiTouchConfigEntry = ConfigEntry[RinnaiTouchCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: RinnaiTouchConfigEntry
) -> bool:
    """Start the passive coordinator for one module; no platforms yet."""
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
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RinnaiTouchConfigEntry
) -> bool:
    """Shut the coordinator down; runtime data is dropped with the entry."""
    await entry.runtime_data.async_shutdown()
    return True
