"""Diagnostics support for Yale Smart Alarm CE."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import YaleConfigEntry

TO_REDACT_CONFIG: set[str] = {
    "email",
    "password",
    "access_token",
    "step_token",
    "api_key",
    "install_id",
}

TO_REDACT_DATA: set[str] = {
    "_id",
    "alarmID",
    "doorbellID",
    "serialNumber",
    "macAddress",
    "identifier",
    "location",
    "LockName",
    "HouseName",
    "name",
    "pubsubChannel",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config_entry": async_redact_data(entry.data, TO_REDACT_CONFIG),
        "coordinator_data": async_redact_data(
            coordinator.data, TO_REDACT_DATA,
        ),
    }
