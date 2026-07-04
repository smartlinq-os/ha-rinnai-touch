"""Shared bases for the Rinnai Touch read-only entity layer.

Everything an entity may read arrives through
:class:`~.coordinator.RinnaiTouchCoordinator`; nothing here touches the
client, the frame parser, or any socket, and no entity exposes a write,
command, refresh, or keepalive path of any kind.

Two deliberately distinct availability contracts (docs/entity_model.md,
coordinator module docstring "Availability contract"):

Health entities (:class:`RinnaiTouchHealthEntity`)
    Describe the integration's own health — connectivity, data freshness,
    last-valid-status time. They are *always* available, because their
    whole purpose is to keep reporting while there is no data, the data is
    stale, or the socket is down. Absent values render as unknown, never
    as fabricated state.

Snapshot entities (:class:`RinnaiTouchSnapshotEntity`)
    Mirror single fields of the current :class:`~.models.StatusSnapshot`.
    Available only while a snapshot exists *and* the coordinator's
    monotonic freshness is FRESH: NO_DATA and STALE both read unavailable.
    Connection state is never an availability input — a disconnect inside
    the fresh window leaves them available, and a silent-but-connected
    socket expires them on time — and ``last_update_success`` is not part
    of the contract either.

Identity is registry-stable by design (docs/entity_model.md "Stable Naming
and Unique-ID Strategy"): unique IDs are ``{config entry ID}_{fixed key}``
and the single module device is keyed on the config-entry ID alone. Host,
IP, entry title, capabilities, and protocol contents never contribute to
either identifier.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Freshness, RinnaiTouchCoordinator


class RinnaiTouchEntity(CoordinatorEntity[RinnaiTouchCoordinator]):
    """Identity and passivity shared by every Rinnai Touch entity.

    Concrete entities derive from exactly one of the two availability
    bases below; this class is never used directly, so the base
    ``CoordinatorEntity`` availability (``last_update_success``) is always
    overridden.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RinnaiTouchCoordinator,
        entry: ConfigEntry,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Rinnai",
        )

    async def async_update(self) -> None:
        """Deliberate no-op: state is push-only and reads have no effects.

        ``CoordinatorEntity.async_update`` would call
        ``async_request_refresh``. This integration has no update method
        and no entity may ever trigger a connection, refresh, or any other
        client activity, so an explicit ``homeassistant.update_entity``
        service call only rewrites the currently known state.
        """


class RinnaiTouchHealthEntity(RinnaiTouchEntity):
    """Base for entities reporting integration health: always available."""

    @property
    def available(self) -> bool:
        """Health state must survive NO_DATA, staleness, and dead sockets."""
        return True


class RinnaiTouchSnapshotEntity(RinnaiTouchEntity):
    """Base for entities mirroring fields of the current status snapshot."""

    @property
    def available(self) -> bool:
        """Fresh valid snapshot required; socket state plays no part."""
        coordinator = self.coordinator
        return (
            coordinator.data is not None
            and coordinator.freshness is Freshness.FRESH
        )
