"""Yale Smart Alarm CE select platform."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory

from .const import SIREN_TYPES, VOLUME_OPTIONS
from .entity import YaleAlarmEntity, YaleDeviceEntity, setup_dynamic_platform
from .error_handler import async_handle_errors

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import AlarmData, YaleConfigEntry, YaleDataUpdateCoordinator

# Limit parallel action calls to the Yale cloud API.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class YaleAlarmSelectDescription(SelectEntityDescription):
    """Describe an alarm-level select entity."""

    setting_key: str


ALARM_VOLUME_SELECTS: tuple[YaleAlarmSelectDescription, ...] = (
    YaleAlarmSelectDescription(
        key="siren_volume",
        translation_key="siren_volume",
        setting_key="sirenVolume",
    ),
    YaleAlarmSelectDescription(
        key="chime_volume",
        translation_key="chime_volume",
        setting_key="chimeVolume",
    ),
    YaleAlarmSelectDescription(
        key="trouble_volume",
        translation_key="trouble_volume",
        setting_key="troubleVolume",
    ),
)


def _create_alarm_selects(
    coordinator: YaleDataUpdateCoordinator,
    alarm_id: str,
    alarm_info: dict[str, Any],
    known_keys: set[str],
    entities: list[SelectEntity],
) -> None:
    """Create alarm-level volume selects."""
    for desc in ALARM_VOLUME_SELECTS:
        if desc.setting_key in alarm_info:
            key = f"{alarm_id}_{desc.setting_key}"
            if key not in known_keys:
                known_keys.add(key)
                entities.append(YaleAlarmVolumeSelect(coordinator, alarm_id, desc))


def _create_device_selects(
    coordinator: YaleDataUpdateCoordinator,
    alarm_id: str,
    alarm_data: AlarmData,
    known_keys: set[str],
    entities: list[SelectEntity],
) -> None:
    """Create device-level siren volume selects."""
    for device in alarm_data.get("device_index", {}).values():
        device_id = device.get("_id")
        if not device_id:
            continue
        if device.get("type") in SIREN_TYPES:
            key = f"{device_id}_volume"
            if key not in known_keys:
                known_keys.add(key)
                entities.append(YaleSirenVolumeSelect(coordinator, alarm_id, device))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yale select entities."""

    def _create_entities(
        coordinator: YaleDataUpdateCoordinator, known_keys: set[str],
    ) -> list[SelectEntity]:
        """Create entities for all current devices, skipping already-known ones."""
        entities: list[SelectEntity] = []
        for alarm_id, alarm_data in coordinator.data["alarms"].items():
            alarm_info = alarm_data.get("info") or {}
            _create_alarm_selects(coordinator, alarm_id, alarm_info, known_keys, entities)
            _create_device_selects(coordinator, alarm_id, alarm_data, known_keys, entities)
        return entities

    setup_dynamic_platform(entry, async_add_entities, _create_entities)


class YaleAlarmVolumeSelect(YaleAlarmEntity, SelectEntity):
    """Represent an alarm-level volume setting."""

    entity_description: YaleAlarmSelectDescription
    _attr_options = VOLUME_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        description: YaleAlarmSelectDescription,
    ) -> None:
        """Initialize the YaleAlarmVolumeSelect."""
        super().__init__(coordinator, alarm_id)
        self.entity_description = description
        self._attr_unique_id = f"{alarm_id}_{description.setting_key}"

    @property
    def current_option(self) -> str | None:
        """Return the current volume level."""
        return self.alarm_info.get(self.entity_description.setting_key)

    @async_handle_errors("set alarm volume")
    async def async_select_option(self, option: str) -> None:
        """Select a volume level."""
        await self.coordinator.async_update_alarm_settings(
            self._alarm_id, {self.entity_description.setting_key: option},
        )


class YaleSirenVolumeSelect(YaleDeviceEntity, SelectEntity):
    """Represent a siren device volume setting."""

    _attr_options = VOLUME_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        device: dict[str, Any],
    ) -> None:
        """Initialize the YaleSirenVolumeSelect."""
        super().__init__(coordinator, alarm_id, device)
        self._attr_unique_id = f"{self._device_id}_volume"
        self._attr_translation_key = "siren_device_volume"

    @property
    def current_option(self) -> str | None:
        """Return the current volume level."""
        return self.device_data.get("volume")

    @async_handle_errors("set siren volume")
    async def async_select_option(self, option: str) -> None:
        """Select a volume level."""
        await self.coordinator.async_update_device(
            self._alarm_id, self._device_id,
            self._build_device_update(volume=option),
        )
