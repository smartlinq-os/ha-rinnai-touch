"""Read-only diagnostic sensors for the Rinnai Touch integration.

Four sensors per module device (docs/entity_model.md, approved Commit 10
scope), all diagnostic-category and enabled by default:

Health (always available)
    ``data_freshness`` — the coordinator's :class:`~.coordinator.Freshness`
    value as an enum sensor over the closed option set ``no_data`` /
    ``fresh`` / ``stale``. Deliberately distinct from the connectivity
    binary sensor: a connected socket says nothing about recent valid
    status data, and vice versa.

    ``last_valid_status`` — UTC wall-clock arrival of the last valid frame
    (the sensor the coordinator's ``last_valid_frame_at`` property is
    reserved for). Unknown until the first valid frame of this runtime.

Fresh-snapshot only
    ``operating_mode`` and ``controller_state`` — the raw protocol codes
    from ``SYST.OSS`` (``MD`` / ``ST``), exposed verbatim: no enum device
    class, no interpretation, and unknown codes pass through unchanged
    because the value sets are not hardware-validated. A field missing
    from an otherwise fresh snapshot reads unknown — never unavailable and
    never fabricated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RinnaiTouchConfigEntry
from .coordinator import Freshness, RinnaiTouchCoordinator
from .entity import RinnaiTouchHealthEntity, RinnaiTouchSnapshotEntity
from .models import StatusSnapshot


@dataclass(frozen=True, kw_only=True)
class RinnaiHealthSensorDescription(SensorEntityDescription):
    """Health sensor: reads the coordinator's always-valid surface."""

    value_fn: Callable[[RinnaiTouchCoordinator], str | datetime | None]


@dataclass(frozen=True, kw_only=True)
class RinnaiSnapshotSensorDescription(SensorEntityDescription):
    """Snapshot sensor: reads one raw field of a status snapshot."""

    value_fn: Callable[[StatusSnapshot], str | None]


HEALTH_SENSORS: Final = (
    RinnaiHealthSensorDescription(
        key="data_freshness",
        translation_key="data_freshness",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[freshness.value for freshness in Freshness],
        value_fn=lambda coordinator: coordinator.freshness.value,
    ),
    RinnaiHealthSensorDescription(
        key="last_valid_status",
        translation_key="last_valid_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator: coordinator.last_valid_frame_at,
    ),
)

SNAPSHOT_SENSORS: Final = (
    RinnaiSnapshotSensorDescription(
        key="operating_mode",
        translation_key="operating_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: snapshot.operating_mode,
    ),
    RinnaiSnapshotSensorDescription(
        key="controller_state",
        translation_key="controller_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: snapshot.controller_state,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RinnaiTouchConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the fixed read-only sensor inventory for one module."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        RinnaiHealthSensor(coordinator, entry, description)
        for description in HEALTH_SENSORS
    ]
    entities.extend(
        RinnaiSnapshotSensor(coordinator, entry, description)
        for description in SNAPSHOT_SENSORS
    )
    async_add_entities(entities)


class RinnaiHealthSensor(RinnaiTouchHealthEntity, SensorEntity):
    """Always-available sensor over the coordinator's health surface."""

    entity_description: RinnaiHealthSensorDescription

    @property
    def native_value(self) -> str | datetime | None:
        """Health value from the coordinator; None renders as unknown."""
        return self.entity_description.value_fn(self.coordinator)


class RinnaiSnapshotSensor(RinnaiTouchSnapshotEntity, SensorEntity):
    """Fresh-snapshot sensor exposing one raw protocol status field."""

    entity_description: RinnaiSnapshotSensorDescription

    @property
    def native_value(self) -> str | None:
        """Raw field value, or None (unknown) when the field is absent."""
        snapshot = self.coordinator.data
        if snapshot is None:
            return None
        return self.entity_description.value_fn(snapshot)
