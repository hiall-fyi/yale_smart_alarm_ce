"""Yale Smart Alarm CE control panel platform."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.components.alarm_control_panel import (  # type: ignore[attr-defined]
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)

from .const import ARM_STATE_DISARM, ARM_STATE_FULL, ARM_STATE_PARTIAL
from .entity import YaleAlarmEntity, setup_dynamic_platform
from .error_handler import async_handle_errors

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import YaleConfigEntry, YaleDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Limit parallel action calls to the Yale cloud API.
PARALLEL_UPDATES = 1

_ARM_STATE_MAP: dict[str, AlarmControlPanelState] = {
    ARM_STATE_DISARM: AlarmControlPanelState.DISARMED,
    ARM_STATE_PARTIAL: AlarmControlPanelState.ARMED_HOME,
    ARM_STATE_FULL: AlarmControlPanelState.ARMED_AWAY,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yale alarm control panel entities."""

    def _create_entities(
        coordinator: YaleDataUpdateCoordinator, known_keys: set[str],
    ) -> list[YaleAlarmControlPanel]:
        """Create entities for all current alarm areas, skipping already-known ones."""
        entities: list[YaleAlarmControlPanel] = []
        for alarm_id, alarm_data in coordinator.data["alarms"].items():
            info = alarm_data.get("info") or {}
            status = info.get("status") or {}
            areas = status.get("areaArmState") or []
            for area in areas:
                area_id = area.get("areaID")
                if not area_id:
                    continue
                key = f"{alarm_id}_{area_id}"
                if key not in known_keys:
                    known_keys.add(key)
                    area_name = area.get("name") if len(areas) > 1 else None
                    entities.append(
                        YaleAlarmControlPanel(coordinator, alarm_id, area_id, area_name),
                    )
        return entities

    setup_dynamic_platform(entry, async_add_entities, _create_entities)


class YaleAlarmControlPanel(YaleAlarmEntity, AlarmControlPanelEntity):
    """Represent a Yale alarm control panel area."""

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        alarm_id: str,
        area_id: str,
        area_name: str | None = None,
    ) -> None:
        """Initialize the YaleAlarmControlPanel."""
        super().__init__(coordinator, alarm_id)
        self._area_id = area_id
        self._attr_unique_id = f"{alarm_id}_{area_id}"
        if area_name:
            # Multi-area: use area name directly so each zone is distinguishable
            self._attr_name = area_name
        else:
            self._attr_translation_key = "alarm"

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the current arm state.

        Priority order:
        1. Triggered — always takes priority.
        2. Exit delay active — show ARMING while the countdown runs.
        3. Arm state from API — normal armed/disarmed state.

        Returns None when the state cannot be determined (shows
        "unknown" in the UI).
        """
        # Check triggered FIRST — triggered always takes priority
        for area in self.alarm_status.get("areaAlarmState") or []:
            if area.get("areaID") == self._area_id and area.get("inAlarm"):
                return AlarmControlPanelState.TRIGGERED

        # Check exit delay — arming in progress.
        # exitTime comes from the arm command response (not polling data),
        # stored on the coordinator as _exit_delay_end_ms.
        exit_end_ms = self.coordinator.exit_delay_end_ms
        if exit_end_ms > 0:
            now_ms = datetime.now(tz=UTC).timestamp() * 1000
            if exit_end_ms > now_ms:
                return AlarmControlPanelState.ARMING

        # Then check arm state
        for area in self.alarm_status.get("areaArmState") or []:
            if area.get("areaID") == self._area_id:
                state = area.get("state")
                mapped = _ARM_STATE_MAP.get(state)
                if mapped is not None:
                    return mapped
                _LOGGER.warning("Alarm reported unrecognised arm state: %s", state)
                return None

        # Area not found — state unknown
        _LOGGER.debug(
            "Area %s not found in alarm %s status data",
            self._area_id,
            self._alarm_id,
        )
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return extra state attributes including exit delay end time."""
        exit_end_ms = self.coordinator.exit_delay_end_ms
        if exit_end_ms > 0:
            try:
                dt = datetime.fromtimestamp(exit_end_ms / 1000, tz=UTC)
                return {"exit_delay_end": dt.isoformat()}
            except (OSError, ValueError, OverflowError):
                pass
        return {"exit_delay_end": None}

    @async_handle_errors("disarm alarm")
    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        await self.coordinator.async_disarm(self._alarm_id, [self._area_id])

    @async_handle_errors("arm home")
    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm-home command."""
        await self.coordinator.async_arm_home(self._alarm_id, [self._area_id])

    @async_handle_errors("arm away")
    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm-away command."""
        await self.coordinator.async_arm_away(self._alarm_id, [self._area_id])
