"""Yale Smart Alarm CE integration for Home Assistant."""
from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

import probatio as vol
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CMD_FULL_ARM, CMD_PARTIAL_ARM, DOMAIN
from .coordinator import AlarmData, YaleConfigEntry, YaleDataUpdateCoordinator
from .entity import (
    build_alarm_hub_device_info,
    clear_cached_hub_device_id,
    set_cached_hub_device_id,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.LOCK,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Force arm service constants
SERVICE_FORCE_ARM = "force_arm"
ATTR_CODE = "code"
ATTR_BYPASS_DEVICES = "bypass_devices"

SERVICE_FORCE_ARM_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
    vol.Required(ATTR_CODE): vol.In(["home", "away"]),
    vol.Required(ATTR_BYPASS_DEVICES): vol.All(
        cv.ensure_list, [cv.string],
    ),
})


async def async_setup_entry(hass: HomeAssistant, entry: YaleConfigEntry) -> bool:
    """Set up Yale Smart Alarm CE from a config entry."""
    coordinator = YaleDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    _register_alarm_hub_devices(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Register force_arm service (once, guarded by service existence check).
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_ARM):
        async def _async_handle_force_arm(call: ServiceCall) -> None:
            """Handle the force_arm service call."""
            entity_id: str = call.data["entity_id"]
            arm_code: str = call.data[ATTR_CODE]
            bypass_devices: list[str] = call.data[ATTR_BYPASS_DEVICES]

            # Map arm code to API command.
            state_cmd = CMD_PARTIAL_ARM if arm_code == "home" else CMD_FULL_ARM

            # Find the entity's config entry to get the coordinator.
            entity_registry = er.async_get(hass)
            entity_entry = entity_registry.async_get(entity_id)
            if not entity_entry or entity_entry.platform != DOMAIN:
                msg = f"Entity {entity_id} does not belong to {DOMAIN}"
                raise ServiceValidationError(msg)

            if entity_entry.config_entry_id is None:
                msg = f"Entity {entity_id} has no config entry"
                raise ServiceValidationError(msg)

            config_entry = hass.config_entries.async_get_entry(
                entity_entry.config_entry_id,
            )
            if not config_entry or not hasattr(config_entry, "runtime_data"):
                msg = f"Integration not loaded for {entity_id}"
                raise ServiceValidationError(msg)

            coord: YaleDataUpdateCoordinator = config_entry.runtime_data

            # Extract alarm_id from the entity unique_id.
            # Format: "{alarm_id}_{area_id}", alarm_id is 32-char hex (no underscores).
            unique_id = entity_entry.unique_id or ""
            alarm_id = unique_id.split("_")[0] if unique_id else ""
            if not alarm_id or alarm_id not in coord.data.get("alarms", {}):
                msg = f"Cannot determine alarm ID for {entity_id}"
                raise ServiceValidationError(msg)

            # Source area IDs from areaArmState, same as alarm_control_panel.
            alarm_data = coord.data["alarms"][alarm_id]
            info = alarm_data.get("info") or {}
            status = info.get("status") or {}
            area_ids = [
                a["areaID"]
                for a in status.get("areaArmState") or []
                if a.get("areaID")
            ]
            if not area_ids:
                msg = (
                    f"No areas available for {entity_id}, the alarm has "
                    "not yet returned area state from Yale, try again in a "
                    "few seconds"
                )
                raise ServiceValidationError(msg)

            await coord.async_force_arm(alarm_id, area_ids, state_cmd, bypass_devices)

        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCE_ARM,
            _async_handle_force_arm,
            schema=SERVICE_FORCE_ARM_SCHEMA,
        )

    return True


def _register_alarm_hub_devices(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
    coordinator: YaleDataUpdateCoordinator,
) -> None:
    """Pre-register every alarm hub so its attached devices can reference it via_device_id.

    One config entry can carry several alarms, so every alarm_id needs its own
    pre-registration and its own cached registry id, not just one.
    """
    device_registry = dr.async_get(hass)
    alarms: dict[str, AlarmData] = coordinator.data.get("alarms") or {}
    for alarm_id, alarm in alarms.items():
        try:
            hub_info = build_alarm_hub_device_info(alarm_id, alarm.get("info") or {})
            device_entry = device_registry.async_get_or_create(
                config_entry_id=entry.entry_id, **hub_info,
            )
            set_cached_hub_device_id(alarm_id, device_entry.id)
        except HomeAssistantError:
            _LOGGER.warning(
                "Setup: could not pre-register alarm hub %s, its devices will "
                "register unparented this session",
                alarm_id,
                exc_info=True,
            )
        entry.async_on_unload(
            functools.partial(clear_cached_hub_device_id, alarm_id),
        )


async def _async_options_updated(hass: HomeAssistant, entry: YaleConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: YaleConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Unregister service if this is the last config entry.
    if unload_ok:
        loaded_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state.name == "LOADED"
        ]
        if not loaded_entries:
            hass.services.async_remove(DOMAIN, SERVICE_FORCE_ARM)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: YaleConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow manual removal of a device if it is no longer present."""
    coordinator = config_entry.runtime_data
    # Check if any of the device's identifiers are still in coordinator data.
    # NOTE: If the coordinator has never successfully fetched data (e.g.
    # persistent auth failure), previous_device_ids is empty and all
    # devices become removable.  This is intentional: a non-functional
    # coordinator cannot verify which devices still exist, so we allow
    # the user to clean up manually.
    for identifier in device_entry.identifiers:
        if identifier[0] != DOMAIN:
            continue
        device_id = identifier[1]
        if device_id in coordinator.previous_device_ids:
            return False
    return True
