"""Yale Smart Alarm CE sensor platform."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory

from .entity import YaleAlarmEntity, YaleLockEntity, setup_dynamic_platform

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import YaleConfigEntry, YaleDataUpdateCoordinator

# Coordinator centralises data updates — no per-entity parallel limit needed.
PARALLEL_UPDATES = 0


# ---------------------------------------------------------------------------
# Value extraction helpers
# ---------------------------------------------------------------------------


def _lock_battery_value(details: dict[str, Any]) -> int | None:
    """Extract lock battery percentage from lock details.

    The Yale API returns a 0.0-1.0 fraction.  Values > 1 are treated
    as already-percentage (defensive guard against API changes).
    """
    battery: float | None = details.get("battery")
    if battery is None:
        return None
    if battery > 1:
        return max(0, min(round(battery), 100))
    return max(0, min(round(battery * 100), 100))


# ---------------------------------------------------------------------------
# EntityDescription definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class YaleAlarmSensorDescription(SensorEntityDescription):
    """Describe an alarm-hub-level sensor."""

    value_fn: Callable[[dict[str, Any]], str | float | int | None]
    use_alarm_info: bool = False


ALARM_SENSORS: tuple[YaleAlarmSensorDescription, ...] = (
    YaleAlarmSensorDescription(
        key="battery",
        translation_key="hub_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("batteryCharge"),
    ),

    YaleAlarmSensorDescription(
        key="cellular_status",
        translation_key="cellular_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.get("cellularConnectionStatus"),
    ),
    YaleAlarmSensorDescription(
        key="timezone",
        translation_key="timezone",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        use_alarm_info=True,
        value_fn=lambda info: info.get("timeZone"),
    ),
)


@dataclass(frozen=True, kw_only=True)
class YaleLockSensorDescription(SensorEntityDescription):
    """Describe a lock-level sensor."""

    value_fn: Callable[[dict[str, Any]], str | float | int | None]


LOCK_SENSORS: tuple[YaleLockSensorDescription, ...] = (
    YaleLockSensorDescription(
        key="battery",
        translation_key="lock_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_lock_battery_value,
    ),
    YaleLockSensorDescription(
        key="battery_state",
        translation_key="lock_battery_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: (d.get("batteryInfo") or {}).get("state"),
    ),
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


def _create_alarm_sensors(
    coordinator: YaleDataUpdateCoordinator,
    alarm_id: str,
    known_keys: set[str],
    entities: list[SensorEntity],
) -> None:
    """Create alarm-hub-level sensors."""
    for alarm_desc in ALARM_SENSORS:
        key = f"{alarm_id}_{alarm_desc.key}"
        if key not in known_keys:
            known_keys.add(key)
            entities.append(YaleAlarmSensor(coordinator, alarm_id, alarm_desc))


def _create_lock_sensors(
    coordinator: YaleDataUpdateCoordinator,
    known_keys: set[str],
    entities: list[SensorEntity],
) -> None:
    """Create lock-level sensors."""
    for lock_id in coordinator.data.get("locks", {}):
        for lock_desc in LOCK_SENSORS:
            key = f"{lock_id}_{lock_desc.key}"
            if key not in known_keys:
                known_keys.add(key)
                entities.append(YaleLockSensor(coordinator, lock_id, lock_desc))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yale sensor entities."""

    def _create_entities(
        coordinator: YaleDataUpdateCoordinator, known_keys: set[str],
    ) -> list[SensorEntity]:
        """Create entities for all current devices, skipping already-known ones."""
        entities: list[SensorEntity] = []
        for alarm_id in coordinator.data["alarms"]:
            _create_alarm_sensors(coordinator, alarm_id, known_keys, entities)
        _create_lock_sensors(coordinator, known_keys, entities)
        return entities

    setup_dynamic_platform(entry, async_add_entities, _create_entities)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------


class YaleAlarmSensor(YaleAlarmEntity, SensorEntity):
    """Represent an alarm-hub-level sensor."""

    entity_description: YaleAlarmSensorDescription

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        description: YaleAlarmSensorDescription,
    ) -> None:
        """Initialize the YaleAlarmSensor."""
        super().__init__(coordinator, alarm_id)
        self.entity_description = description
        self._attr_unique_id = f"{alarm_id}_{description.key}"

    @property
    def native_value(self) -> str | float | int | None:
        """Return the sensor value."""
        source = self.alarm_info if self.entity_description.use_alarm_info else self.alarm_status
        return self.entity_description.value_fn(source)


class YaleLockSensor(YaleLockEntity, SensorEntity):
    """Represent a lock-level sensor."""

    entity_description: YaleLockSensorDescription

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        lock_id: str,
        description: YaleLockSensorDescription,
    ) -> None:
        """Initialize the YaleLockSensor."""
        super().__init__(coordinator, lock_id)
        self.entity_description = description
        self._attr_unique_id = f"{lock_id}_{description.key}"

    @property
    def native_value(self) -> str | float | int | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.lock_details)
