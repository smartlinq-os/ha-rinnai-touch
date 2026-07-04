"""Read-only diagnostic binary sensors for the Rinnai Touch integration.

Two binary sensors per module device (docs/entity_model.md, approved
Commit 10 scope), both diagnostic-category and enabled by default:

Health (always available)
    ``connectivity`` — on exactly while the passive client's socket state
    is CONNECTED. Deliberately distinct from data freshness: a connected
    socket says nothing about recent valid status data, and vice versa
    (coordinator module docstring, "Availability contract").

Fresh-snapshot only
    ``fault_active`` — the ``SYST.FLT.AV`` Y/N flag as parsed into
    :class:`~.models.FaultRecord`. Unknown when the flag is absent or
    unrecognised in an otherwise fresh snapshot; no fault meaning, code,
    or severity is interpreted here.

The ``ConnectionState`` import from the pure client layer is read-only
enum access for the connectivity comparison; no entity module constructs
or manages a client (locked in tests/test_project_structure.py).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RinnaiTouchConfigEntry
from .client import ConnectionState
from .coordinator import RinnaiTouchCoordinator
from .entity import RinnaiTouchHealthEntity, RinnaiTouchSnapshotEntity
from .models import StatusSnapshot


@dataclass(frozen=True, kw_only=True)
class RinnaiHealthBinarySensorDescription(BinarySensorEntityDescription):
    """Health binary sensor: reads the coordinator's always-valid surface."""

    value_fn: Callable[[RinnaiTouchCoordinator], bool | None]


@dataclass(frozen=True, kw_only=True)
class RinnaiSnapshotBinarySensorDescription(BinarySensorEntityDescription):
    """Snapshot binary sensor: reads one parsed flag of a status snapshot."""

    value_fn: Callable[[StatusSnapshot], bool | None]


HEALTH_BINARY_SENSORS: Final = (
    RinnaiHealthBinarySensorDescription(
        key="connectivity",
        translation_key="connectivity",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=(
            lambda coordinator: coordinator.connection_state
            is ConnectionState.CONNECTED
        ),
    ),
)

SNAPSHOT_BINARY_SENSORS: Final = (
    RinnaiSnapshotBinarySensorDescription(
        key="fault_active",
        translation_key="fault_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda snapshot: snapshot.fault.active,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RinnaiTouchConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the fixed read-only binary-sensor inventory for one module."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        RinnaiHealthBinarySensor(coordinator, entry, description)
        for description in HEALTH_BINARY_SENSORS
    ]
    entities.extend(
        RinnaiSnapshotBinarySensor(coordinator, entry, description)
        for description in SNAPSHOT_BINARY_SENSORS
    )
    async_add_entities(entities)


class RinnaiHealthBinarySensor(RinnaiTouchHealthEntity, BinarySensorEntity):
    """Always-available binary sensor over the coordinator's health."""

    entity_description: RinnaiHealthBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Health flag from the coordinator."""
        return self.entity_description.value_fn(self.coordinator)


class RinnaiSnapshotBinarySensor(RinnaiTouchSnapshotEntity, BinarySensorEntity):
    """Fresh-snapshot binary sensor exposing one parsed status flag."""

    entity_description: RinnaiSnapshotBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Flag value, or None (unknown) when the field is absent."""
        snapshot = self.coordinator.data
        if snapshot is None:
            return None
        return self.entity_description.value_fn(snapshot)
