"""Yale Smart Alarm CE binary sensor platform."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .const import (
    CONTACT_SENSOR_TYPES,
    DEVICE_TYPE_RF_BUTTON,
    DEVICE_TYPE_SMOKE,
    MOTION_SENSOR_TYPES,
)
from .entity import YaleAlarmEntity, YaleDeviceEntity, YaleDoorbellEntity, YaleLockEntity, setup_dynamic_platform

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import AlarmData, YaleConfigEntry, YaleDataUpdateCoordinator

# Coordinator centralises data updates — no per-entity parallel limit needed.
PARALLEL_UPDATES = 0


# ---------------------------------------------------------------------------
# EntityDescription definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class YaleDeviceBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Yale device-level binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool]
    device_types: frozenset[str] | None = None
    requires_key: str | None = None


DEVICE_BINARY_SENSORS: tuple[YaleDeviceBinarySensorDescription, ...] = (
    YaleDeviceBinarySensorDescription(
        key="contact",
        translation_key="contact",
        device_class=BinarySensorDeviceClass.DOOR,
        device_types=CONTACT_SENSOR_TYPES,
        value_fn=lambda s: s.get("contactOpen", False),
    ),
    YaleDeviceBinarySensorDescription(
        key="motion",
        translation_key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        device_types=MOTION_SENSOR_TYPES,
        # Yale PIR sensors report motion via contactOpen (same as contact sensors).
        # This is confirmed by the Yale Home app API responses.
        value_fn=lambda s: s.get("contactOpen", False),
    ),
    YaleDeviceBinarySensorDescription(
        key="smoke",
        translation_key="smoke",
        device_class=BinarySensorDeviceClass.SMOKE,
        device_types=frozenset({DEVICE_TYPE_SMOKE}),
        value_fn=lambda s: s.get("fault", False) or s.get("smokeDetected", False),
    ),
    YaleDeviceBinarySensorDescription(
        key="panic",
        translation_key="panic",
        device_class=BinarySensorDeviceClass.SAFETY,
        device_types=frozenset({DEVICE_TYPE_RF_BUTTON}),
        value_fn=lambda s: s.get("contactOpen", False),
    ),
    YaleDeviceBinarySensorDescription(
        key="battery",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("lowBattery", False),
    ),
    YaleDeviceBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("online", False),
    ),
    YaleDeviceBinarySensorDescription(
        key="tamper",
        translation_key="tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_category=EntityCategory.DIAGNOSTIC,
        requires_key="tamperEnabled",
        value_fn=lambda s: s.get("tamperOpen", False),
    ),
)


@dataclass(frozen=True, kw_only=True)
class YaleAlarmBinarySensorDescription(BinarySensorEntityDescription):
    """Describe an alarm-hub-level binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool]


ALARM_BINARY_SENSORS: tuple[YaleAlarmBinarySensorDescription, ...] = (
    YaleAlarmBinarySensorDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("connected", False),
    ),
    YaleAlarmBinarySensorDescription(
        key="tamper",
        translation_key="hub_tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("tamperOpen", False),
    ),
    YaleAlarmBinarySensorDescription(
        key="rf_jamming",
        translation_key="rf_jamming",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.get("rfJamming", False),
    ),
    YaleAlarmBinarySensorDescription(
        key="in_alarm",
        translation_key="in_alarm",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda s: any(a.get("inAlarm") for a in s.get("areaAlarmState") or []),
    ),
    YaleAlarmBinarySensorDescription(
        key="ethernet",
        translation_key="ethernet",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.get("ethernetStatus") == "ETHERNET_STATUS_CONNECTED",
    ),
    YaleAlarmBinarySensorDescription(
        key="test_mode",
        translation_key="test_mode",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.get("testModeEnabled", False),
    ),
)


@dataclass(frozen=True, kw_only=True)
class YaleLockBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a lock-level binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool | None]
    source: str = "details"


LOCK_BINARY_SENSORS: tuple[YaleLockBinarySensorDescription, ...] = (
    YaleLockBinarySensorDescription(
        key="supports_entry_codes",
        translation_key="supports_entry_codes",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        source="details",
        value_fn=lambda d: d.get("supportsEntryCodes"),
    ),
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


def _create_alarm_binary_sensors(
    coordinator: YaleDataUpdateCoordinator,
    alarm_id: str,
    known_keys: set[str],
    entities: list[BinarySensorEntity],
) -> None:
    """Create alarm-hub-level binary sensors."""
    for alarm_desc in ALARM_BINARY_SENSORS:
        key = f"{alarm_id}_{alarm_desc.key}"
        if key not in known_keys:
            known_keys.add(key)
            entities.append(YaleAlarmBinarySensor(coordinator, alarm_id, alarm_desc))


def _create_device_binary_sensors(
    coordinator: YaleDataUpdateCoordinator,
    alarm_id: str,
    alarm_data: AlarmData,
    known_keys: set[str],
    entities: list[BinarySensorEntity],
) -> None:
    """Create device-level binary sensors for an alarm's devices."""
    for device in alarm_data.get("device_index", {}).values():
        device_id = device.get("_id")
        if not device_id:
            continue
        device_type = device.get("type", "")
        for dev_desc in DEVICE_BINARY_SENSORS:
            if dev_desc.device_types is not None and device_type not in dev_desc.device_types:
                continue
            if dev_desc.requires_key and device.get(dev_desc.requires_key) is None:
                continue
            key = f"{device_id}_{dev_desc.key}"
            if key not in known_keys:
                known_keys.add(key)
                entities.append(YaleDeviceBinarySensor(coordinator, alarm_id, device, dev_desc))


def _create_lock_binary_sensors(
    coordinator: YaleDataUpdateCoordinator,
    known_keys: set[str],
    entities: list[BinarySensorEntity],
) -> None:
    """Create lock door sensors and lock-level binary sensors."""
    for lock_id in coordinator.data.get("locks", {}):
        key = f"{lock_id}_door"
        if key not in known_keys:
            known_keys.add(key)
            entities.append(YaleLockDoorSensor(coordinator, lock_id))
        for lock_desc in LOCK_BINARY_SENSORS:
            key = f"{lock_id}_{lock_desc.key}"
            if key not in known_keys:
                known_keys.add(key)
                entities.append(YaleLockBinarySensor(coordinator, lock_id, lock_desc))


def _create_doorbell_binary_sensors(
    coordinator: YaleDataUpdateCoordinator,
    known_keys: set[str],
    entities: list[BinarySensorEntity],
) -> None:
    """Create doorbell binary sensors."""
    for doorbell_id, doorbell in (coordinator.data.get("doorbells") or {}).items():
        key = f"{doorbell_id}_ding"
        if key not in known_keys:
            known_keys.add(key)
            entities.append(YaleDoorbellBinarySensor(coordinator, doorbell))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yale binary sensor entities."""

    def _create_entities(
        coordinator: YaleDataUpdateCoordinator, known_keys: set[str],
    ) -> list[BinarySensorEntity]:
        """Create entities for all current devices, skipping already-known ones."""
        entities: list[BinarySensorEntity] = []
        for alarm_id, alarm_data in coordinator.data["alarms"].items():
            _create_alarm_binary_sensors(coordinator, alarm_id, known_keys, entities)
            _create_device_binary_sensors(coordinator, alarm_id, alarm_data, known_keys, entities)
        _create_lock_binary_sensors(coordinator, known_keys, entities)
        _create_doorbell_binary_sensors(coordinator, known_keys, entities)
        return entities

    setup_dynamic_platform(entry, async_add_entities, _create_entities)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------


class YaleDeviceBinarySensor(YaleDeviceEntity, BinarySensorEntity):
    """Represent a binary sensor on a Yale alarm device."""

    entity_description: YaleDeviceBinarySensorDescription

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        device: dict[str, Any],
        description: YaleDeviceBinarySensorDescription,
    ) -> None:
        """Initialize the YaleDeviceBinarySensor."""
        super().__init__(coordinator, alarm_id, device)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return False when the feature gate is absent from the device."""
        if not super().available:
            return False
        rk = self.entity_description.requires_key
        return not rk or self.device_data.get(rk) is not None

    @property
    def is_on(self) -> bool:
        """Return True if the binary sensor is on."""
        return self.entity_description.value_fn(self.device_status)


class YaleAlarmBinarySensor(YaleAlarmEntity, BinarySensorEntity):
    """Represent a binary sensor on the alarm hub."""

    entity_description: YaleAlarmBinarySensorDescription

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        description: YaleAlarmBinarySensorDescription,
    ) -> None:
        """Initialize the YaleAlarmBinarySensor."""
        super().__init__(coordinator, alarm_id)
        self.entity_description = description
        self._attr_unique_id = f"{alarm_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return True if the binary sensor is on."""
        return self.entity_description.value_fn(self.alarm_status)


class YaleLockDoorSensor(YaleLockEntity, BinarySensorEntity):
    """Represent the door open/closed sensor on a Yale lock."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        lock_id: str,
    ) -> None:
        """Initialize the YaleLockDoorSensor."""
        super().__init__(coordinator, lock_id)
        self._attr_unique_id = f"{lock_id}_door"
        self._attr_translation_key = "lock_door"

    @property
    def is_on(self) -> bool | None:
        """Return True if the door is open."""
        door_state: str | None = self.lock_status.get("doorState")
        if door_state is None:
            return None
        return door_state == "open"


class YaleLockBinarySensor(YaleLockEntity, BinarySensorEntity):
    """Represent a binary sensor on a Yale lock."""

    entity_description: YaleLockBinarySensorDescription

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        lock_id: str,
        description: YaleLockBinarySensorDescription,
    ) -> None:
        """Initialize the YaleLockBinarySensor."""
        super().__init__(coordinator, lock_id)
        self.entity_description = description
        self._attr_unique_id = f"{lock_id}_{description.key}"

    @property
    def _source_data(self) -> dict[str, Any]:
        """Return the data dict based on the description source."""
        if self.entity_description.source == "status":
            return self.lock_status
        if self.entity_description.source == "data":
            return self.lock_data
        return self.lock_details

    @property
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is on."""
        return self.entity_description.value_fn(self._source_data)


class YaleDoorbellBinarySensor(YaleDoorbellEntity, BinarySensorEntity):
    """Represent a doorbell ding event sensor."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_translation_key = "doorbell_ding"

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        doorbell: dict[str, Any],
    ) -> None:
        """Initialize the YaleDoorbellBinarySensor."""
        super().__init__(coordinator, doorbell)
        self._attr_unique_id = f"{self._doorbell_id}_ding"

    @property
    def is_on(self) -> bool:
        """Return True if a ding event is active."""
        status = self._doorbell_data.get("status") or {}
        return bool(status.get("dingActive", False))
