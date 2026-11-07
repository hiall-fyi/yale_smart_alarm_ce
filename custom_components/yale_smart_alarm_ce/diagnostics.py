"""Diagnostics support for Yale Smart Alarm CE."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

if TYPE_CHECKING:
    from collections.abc import Iterable

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
    "areaID",
    "doorbellID",
    "serialNumber",
    "SerialNumber",
    "macAddress",
    "mac",
    "mfgBridgeID",
    "identifier",
    "identifiers",
    "location",
    "LockID",
    "lockID",
    "LockName",
    "lockName",
    "HouseName",
    "houseName",
    "houseID",
    "HouseID",
    "name",
    "pubsubChannel",
    "pubsubURL",
    "subscriberID",
    # User PII (lock details → users dict, keyfob userID)
    "users",
    "owners",
    "guests",
    "managed",
    "invitations",
    "userID",
    "UserID",
    "callingUserID",
    "FirstName",
    "LastName",
    "firstName",
    "lastName",
    "email",
    "phoneNumber",
    "phone",
    # Lock security / credentials
    "key",
    "pin",
    "pinCode",
    "accessCode",
    "entryCode",
    "accessRules",
    "remoteOperateSecret",
    "hostHardwareID",
    "zwaveDSK",
    "moduleSerialNumber",
    # Network / security secrets (alarm info)
    "wifiPassword",
    "wifiSsid",
    # Device identifiers
    "hubId",
    "systemId",
    "sku",
}


def _build_id_labels(identifiers: Iterable[str], label: str) -> dict[str, str]:
    """Map each identifier to a positional placeholder.

    One shared map per identifier kind, so a lock that appears in some
    sections but not others (a failed per-lock fetch) keeps the same
    placeholder everywhere it does appear.
    """
    return {
        identifier: f"{label}_{index}"
        for index, identifier in enumerate(sorted(identifiers))
    }


def _relabel(mapping: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    """Rewrite a mapping's identifier keys using *labels*."""
    return {labels.get(key, key): value for key, value in mapping.items()}


def _redact_coordinator_data(data: Any) -> dict[str, Any]:
    """Redact coordinator data, including the ID-keyed section keys.

    ``async_redact_data`` rewrites values only, and these sections are
    keyed by the same alarm, lock and device identifiers it scrubs one
    level down.
    """
    redacted: dict[str, Any] = async_redact_data(data, TO_REDACT_DATA)

    lock_ids: set[str] = set()
    for section in ("locks", "lock_status", "lock_details"):
        entries = redacted.get(section)
        if isinstance(entries, dict):
            lock_ids.update(entries)
    lock_labels = _build_id_labels(lock_ids, "lock")
    for section in ("locks", "lock_status", "lock_details"):
        entries = redacted.get(section)
        if isinstance(entries, dict):
            redacted[section] = _relabel(entries, lock_labels)

    alarms = redacted.get("alarms")
    if isinstance(alarms, dict):
        for alarm in alarms.values():
            devices = alarm.get("device_index") if isinstance(alarm, dict) else None
            if isinstance(devices, dict):
                alarm["device_index"] = _relabel(
                    devices, _build_id_labels(devices, "device"),
                )
        redacted["alarms"] = _relabel(alarms, _build_id_labels(alarms, "alarm"))

    return redacted


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config_entry": async_redact_data(entry.data, TO_REDACT_CONFIG),
        "coordinator_data": _redact_coordinator_data(coordinator.data),
    }
