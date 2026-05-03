"""Yale Smart Alarm CE switch platform."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory

from .const import DEVICE_TYPE_KEYPAD, SIREN_TYPES
from .entity import YaleAlarmEntity, YaleDeviceEntity, setup_dynamic_platform
from .error_handler import async_handle_errors

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import AlarmData, YaleConfigEntry, YaleDataUpdateCoordinator

# Limit parallel action calls to the Yale cloud API.
PARALLEL_UPDATES = 1

# ---------------------------------------------------------------------------
# EntityDescription definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class YaleAlarmSwitchDescription(SwitchEntityDescription):
    """Describe an alarm-level boolean switch."""

    setting_key: str


ALARM_SETTING_SWITCHES: tuple[YaleAlarmSwitchDescription, ...] = (
    YaleAlarmSwitchDescription(
        key="white_led", translation_key="white_led", setting_key="whiteLEDEnabled",
    ),
    YaleAlarmSwitchDescription(
        key="tamper_detection", translation_key="tamper_detection", setting_key="tamperEnabled",
    ),
    YaleAlarmSwitchDescription(
        key="rf_jam_detection", translation_key="rf_jam_detection", setting_key="rfJamDetection",
    ),
    YaleAlarmSwitchDescription(
        key="force_arm", translation_key="force_arm", setting_key="forceArm",
    ),
    YaleAlarmSwitchDescription(
        key="cellular_backup", translation_key="cellular_backup", setting_key="cellEnabled",
    ),
    YaleAlarmSwitchDescription(
        key="wifi", translation_key="wifi", setting_key="wifiEnabled",
    ),
    YaleAlarmSwitchDescription(
        key="daylight_savings", translation_key="daylight_savings", setting_key="daylightSavings",
        entity_registry_enabled_default=False,
    ),
    YaleAlarmSwitchDescription(
        key="rf_supervisory", translation_key="rf_supervisory", setting_key="rfSupervisoryEnabled",
        entity_registry_enabled_default=False,
    ),
    YaleAlarmSwitchDescription(
        key="keypad_quickset", translation_key="keypad_quickset", setting_key="rfKeypadQuickset",
        entity_registry_enabled_default=False,
    ),
)


@dataclass(frozen=True, kw_only=True)
class YaleDeviceSwitchDescription(SwitchEntityDescription):
    """Describe a Yale device-level boolean switch."""

    setting_key: str
    device_types: frozenset[str]


DEVICE_SWITCHES: tuple[YaleDeviceSwitchDescription, ...] = (
    YaleDeviceSwitchDescription(
        key="entry_exit_tone",
        translation_key="entry_exit_tone",
        setting_key="entryExitToneEnabled",
        device_types=SIREN_TYPES,
    ),
    YaleDeviceSwitchDescription(
        key="comfort_led",
        translation_key="comfort_led",
        setting_key="comfortLedEnabled",
        device_types=SIREN_TYPES,
    ),
    YaleDeviceSwitchDescription(
        key="strobe",
        translation_key="strobe",
        setting_key="strobeEnabled",
        device_types=SIREN_TYPES,
    ),
    YaleDeviceSwitchDescription(
        key="proximity_wakeup",
        translation_key="proximity_wakeup",
        setting_key="proximityWakeupEnabled",
        device_types=frozenset({DEVICE_TYPE_KEYPAD}),
    ),
)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


def _create_alarm_switches(
    coordinator: YaleDataUpdateCoordinator,
    alarm_id: str,
    alarm_info: dict[str, Any],
    known_keys: set[str],
    entities: list[SwitchEntity],
) -> None:
    """Create alarm-level setting switches."""
    for alarm_desc in ALARM_SETTING_SWITCHES:
        if alarm_desc.setting_key in alarm_info:
            key = f"{alarm_id}_{alarm_desc.setting_key}"
            if key not in known_keys:
                known_keys.add(key)
                entities.append(YaleAlarmSettingSwitch(coordinator, alarm_id, alarm_desc))


def _create_device_switches(
    coordinator: YaleDataUpdateCoordinator,
    alarm_id: str,
    alarm_data: AlarmData,
    known_keys: set[str],
    entities: list[SwitchEntity],
) -> None:
    """Create device-level boolean switches."""
    for device in alarm_data.get("device_index", {}).values():
        device_id = device.get("_id")
        if not device_id:
            continue
        dtype = device.get("type", "")
        for dev_desc in DEVICE_SWITCHES:
            if dtype in dev_desc.device_types:
                key = f"{device_id}_{dev_desc.key}"
                if key not in known_keys:
                    known_keys.add(key)
                    entities.append(YaleDeviceBooleanSwitch(coordinator, alarm_id, device, dev_desc))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yale switch entities."""

    def _create_entities(
        coordinator: YaleDataUpdateCoordinator, known_keys: set[str],
    ) -> list[SwitchEntity]:
        """Create entities for all current devices, skipping already-known ones."""
        entities: list[SwitchEntity] = []
        for alarm_id, alarm_data in coordinator.data["alarms"].items():
            alarm_info = alarm_data.get("info") or {}
            _create_alarm_switches(coordinator, alarm_id, alarm_info, known_keys, entities)
            _create_device_switches(coordinator, alarm_id, alarm_data, known_keys, entities)
        return entities

    setup_dynamic_platform(entry, async_add_entities, _create_entities)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------


class YaleAlarmSettingSwitch(YaleAlarmEntity, SwitchEntity):
    """Represent a boolean alarm setting as a switch."""

    entity_description: YaleAlarmSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        description: YaleAlarmSwitchDescription,
    ) -> None:
        """Initialize the YaleAlarmSettingSwitch."""
        super().__init__(coordinator, alarm_id)
        self.entity_description = description
        self._attr_unique_id = f"{alarm_id}_{description.setting_key}"

    @property
    def is_on(self) -> bool:
        """Return True if the setting is enabled."""
        return bool(self.alarm_info.get(self.entity_description.setting_key, False))

    @async_handle_errors("turn on alarm setting")  # type: ignore[arg-type]
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self.coordinator.async_update_alarm_settings(
            self._alarm_id, {self.entity_description.setting_key: True},
        )

    @async_handle_errors("turn off alarm setting")  # type: ignore[arg-type]
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self.coordinator.async_update_alarm_settings(
            self._alarm_id, {self.entity_description.setting_key: False},
        )


class YaleDeviceBooleanSwitch(YaleDeviceEntity, SwitchEntity):
    """Represent a device-level boolean setting as a switch."""

    entity_description: YaleDeviceSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        device: dict[str, Any],
        description: YaleDeviceSwitchDescription,
    ) -> None:
        """Initialize the YaleDeviceBooleanSwitch."""
        super().__init__(coordinator, alarm_id, device)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return True if the setting is enabled."""
        return bool(self.device_data.get(self.entity_description.setting_key, False))

    @async_handle_errors("enable device setting")  # type: ignore[arg-type]
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self.coordinator.async_update_device(
            self._alarm_id, self._device_id,
            self._build_device_update(**{self.entity_description.setting_key: True}),
        )

    @async_handle_errors("disable device setting")  # type: ignore[arg-type]
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self.coordinator.async_update_device(
            self._alarm_id, self._device_id,
            self._build_device_update(**{self.entity_description.setting_key: False}),
        )
