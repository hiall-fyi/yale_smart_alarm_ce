"""Base entity classes for Yale Smart Alarm CE."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_TYPE_NAMES, DOMAIN, MANUFACTURER
from .coordinator import YaleDataUpdateCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity import Entity
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


def build_device_info(alarm_id: str, device: dict[str, Any]) -> DeviceInfo:
    """Build a DeviceInfo for an alarm-attached device."""
    device_type = device.get("type", "unknown")
    status = device.get("status") or {}
    return DeviceInfo(
        identifiers={(DOMAIN, device["_id"])},
        name=device.get("name", "Yale Device"),
        manufacturer=MANUFACTURER,
        model=DEVICE_TYPE_NAMES.get(device_type, device_type),
        serial_number=device.get("serialNumber"),
        sw_version=status.get("firmwareVersion"),
        via_device=(DOMAIN, alarm_id),
    )


def build_alarm_hub_device_info(
    alarm_id: str, alarm_info: dict[str, Any],
) -> DeviceInfo:
    """Build a DeviceInfo for the alarm hub itself."""
    status = alarm_info.get("status") or {}
    return DeviceInfo(
        identifiers={(DOMAIN, alarm_id)},
        name=f"Yale Alarm Hub ({alarm_info.get('location', alarm_id[-4:])})",
        manufacturer=MANUFACTURER,
        model="Smart Alarm Hub",
        serial_number=alarm_info.get("serialNumber"),
        sw_version=status.get("hubFirmwareVersion"),
    )


def setup_dynamic_platform(
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    create_fn: Callable[[YaleDataUpdateCoordinator, set[str]], Sequence[Entity]],
) -> None:
    """Wire up entity creation and dynamic discovery for a platform.

    Extracts the repeated boilerplate shared by every platform's
    ``async_setup_entry``: initial entity creation, known-key tracking,
    and a coordinator listener that adds newly discovered entities on
    each data refresh.
    """
    coordinator: YaleDataUpdateCoordinator = entry.runtime_data
    known_keys: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        """Add entities for newly discovered devices on coordinator update."""
        new_entities = create_fn(coordinator, known_keys)
        if new_entities:
            async_add_entities(new_entities)

    async_add_entities(create_fn(coordinator, known_keys))
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class YaleAlarmEntity(CoordinatorEntity[YaleDataUpdateCoordinator]):
    """Base entity for alarm-level data (hub sensors, settings, etc.).

    Data structure from coordinator:
        ``alarm_info``  → top-level alarm object (contains settings like
        ``sirenVolume``, ``tamperEnabled``, etc.).
        ``alarm_status`` → ``alarm_info["status"]`` sub-dict (contains
        runtime state like ``connected``, ``batteryCharge``,
        ``areaArmState``, etc.).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
    ) -> None:
        """Initialize the YaleAlarmEntity."""
        super().__init__(coordinator)
        self._alarm_id = alarm_id

    @property
    def alarm_info(self) -> dict[str, Any]:
        """Return the alarm info dict from coordinator data."""
        alarms = self.coordinator.data.get("alarms") or {}
        alarm = alarms.get(self._alarm_id)
        if alarm is None:
            return {}
        return alarm.get("info") or {}

    @property
    def alarm_status(self) -> dict[str, Any]:
        """Return the alarm status sub-dict."""
        return self.alarm_info.get("status") or {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return live device info from coordinator data."""
        return build_alarm_hub_device_info(self._alarm_id, self.alarm_info)

    @property
    def available(self) -> bool:
        """Return False when the alarm has disappeared from the API."""
        return super().available and self._alarm_id in (
            self.coordinator.data.get("alarms") or {}
        )


class YaleDeviceEntity(CoordinatorEntity[YaleDataUpdateCoordinator]):
    """Base entity for a device attached to an alarm."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        device: dict[str, Any],
    ) -> None:
        """Initialize the YaleDeviceEntity."""
        super().__init__(coordinator)
        self._alarm_id = alarm_id
        self._device_id: str = device["_id"]
        self._device_type: str = device.get("type", "unknown")

    @property
    def device_data(self) -> dict[str, Any]:
        """Return the current device dict from coordinator data."""
        alarms = self.coordinator.data.get("alarms") or {}
        alarm_entry = alarms.get(self._alarm_id)
        if alarm_entry is None:
            return {}
        device_index: dict[str, dict[str, Any]] | None = alarm_entry.get("device_index")
        if device_index is not None:
            return device_index.get(self._device_id, {})
        return {}

    @property
    def device_status(self) -> dict[str, Any]:
        """Return the device status sub-dict."""
        return self.device_data.get("status") or {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return live device info from coordinator data."""
        dd = self.device_data
        if dd:
            return build_device_info(self._alarm_id, dd)
        # Fallback: device disappeared from API — return stable identifiers
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name="Yale Device",
            manufacturer=MANUFACTURER,
            via_device=(DOMAIN, self._alarm_id),
        )

    @property
    def available(self) -> bool:
        """Return False when the device has disappeared from the API."""
        return super().available and bool(self.device_data)

    def _build_device_update(self, **settings: Any) -> dict[str, Any]:
        """Build a device update payload with the required 'type' field."""
        return {"type": self._device_type, **settings}


class YaleLockEntity(CoordinatorEntity[YaleDataUpdateCoordinator]):
    """Base entity for a Yale smart lock."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        lock_id: str,
    ) -> None:
        """Initialize the YaleLockEntity."""
        super().__init__(coordinator)
        self._lock_id = lock_id

    @property
    def lock_data(self) -> dict[str, Any]:
        """Return the lock data dict from coordinator."""
        return (self.coordinator.data.get("locks") or {}).get(self._lock_id) or {}

    @property
    def lock_status(self) -> dict[str, Any]:
        """Return the lock status dict from coordinator."""
        return (self.coordinator.data.get("lock_status") or {}).get(self._lock_id) or {}

    @property
    def lock_details(self) -> dict[str, Any]:
        """Return the lock details dict from coordinator."""
        return (
            (self.coordinator.data.get("lock_details") or {})
            .get(self._lock_id) or {}
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return live device info from coordinator data."""
        details = self.lock_details
        info = DeviceInfo(
            identifiers={(DOMAIN, self._lock_id)},
            name=self.lock_data.get("LockName", "Yale Lock"),
            manufacturer=MANUFACTURER,
            model="Smart Lock",
            serial_number=details.get("serialNumber"),
            sw_version=details.get("firmwareVersion"),
        )
        mac: str | None = self.lock_data.get("macAddress")
        if mac:
            info["connections"] = {(CONNECTION_BLUETOOTH, mac)}
        return info

    @property
    def available(self) -> bool:
        """Return False when the lock has disappeared from the API."""
        return super().available and self._lock_id in (
            self.coordinator.data.get("locks") or {}
        )


class YaleDoorbellEntity(CoordinatorEntity[YaleDataUpdateCoordinator]):
    """Base entity for a Yale doorbell."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        doorbell: dict[str, Any],
    ) -> None:
        """Initialize the YaleDoorbellEntity."""
        super().__init__(coordinator)
        self._doorbell_id: str = doorbell.get("_id") or doorbell.get("doorbellID", "")

    @property
    def _doorbell_data(self) -> dict[str, Any]:
        """Return the current doorbell dict from coordinator data."""
        return (self.coordinator.data.get("doorbells") or {}).get(
            self._doorbell_id, {},
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the doorbell."""
        data = self._doorbell_data
        return DeviceInfo(
            identifiers={(DOMAIN, self._doorbell_id)},
            name=data.get("name", "Yale Doorbell"),
            manufacturer=MANUFACTURER,
            model="Doorbell",
        )

    @property
    def available(self) -> bool:
        """Return False when the doorbell has disappeared from the API."""
        return super().available and bool(self._doorbell_data)
