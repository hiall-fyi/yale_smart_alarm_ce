"""Data update coordinator for Yale Smart Alarm CE."""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta
from typing import TYPE_CHECKING, Any, TypedDict, TypeVar

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YaleApiClient
from .const import (
    CONF_API_KEY,
    CONF_INSTALL_ID,
    CONF_REGION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .error_handler import YaleAuthenticationError, YaleError, YaleRateLimitError
from .repair_helpers import (
    async_create_auth_issue,
    async_create_rate_limit_issue,
    async_delete_auth_issue,
    async_delete_rate_limit_issue,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

# Retry configuration for transient API errors
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 5  # seconds
_RETRY_MAX_DELAY = 60  # seconds
_RETRY_BACKOFF_FACTOR = 2

# Delay before a single optimistic re-poll when degraded status is detected
_DEGRADED_REPOLL_DELAY = 15  # seconds

type YaleConfigEntry = ConfigEntry[YaleDataUpdateCoordinator]


class AlarmData(TypedDict):
    """Represent the data for a single alarm."""

    info: dict[str, Any]
    device_index: dict[str, dict[str, Any]]


class YaleCoordinatorData(TypedDict):
    """Represent the top-level coordinator data shape.

    Keys:
        alarms: alarm_id → AlarmData (info + devices + device_index).
        locks: lock_id → raw lock dict from ``GET /users/locks/mine``.
        lock_status: lock_id → raw status dict from ``GET /locks/{id}/status``.
        lock_details: lock_id → raw details dict from ``GET /locks/{id}``.
        doorbells: doorbell_id → raw doorbell dict from ``GET /users/doorbells/mine``.

    Lock dicts remain ``dict[str, Any]`` because the Yale API has no
    formal schema — fields vary by device model and firmware version.
    Typing them more strictly would create a maintenance burden without
    meaningful safety gains.
    """

    alarms: dict[str, AlarmData]
    locks: dict[str, dict[str, Any]]
    lock_status: dict[str, dict[str, Any]]
    lock_details: dict[str, dict[str, Any]]
    doorbells: dict[str, dict[str, Any]]


class YaleDataUpdateCoordinator(DataUpdateCoordinator[YaleCoordinatorData]):
    """Manage fetching Yale data from the API."""

    config_entry: YaleConfigEntry

    def __init__(self, hass: HomeAssistant, entry: YaleConfigEntry) -> None:
        """Initialize the YaleDataUpdateCoordinator."""
        session = async_get_clientsession(hass)
        self.api = YaleApiClient(
            session=session,
            email=entry.data["email"],
            password=entry.data["password"],
            api_key=entry.data.get(CONF_API_KEY),
            region=entry.data.get(CONF_REGION),
            install_id=entry.data.get(CONF_INSTALL_ID),
        )
        self.previous_device_ids: set[str] = set()
        self._degraded_repoll_scheduled: bool = False
        self._exit_delay_end_ms: float = 0

        interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )

    @property
    def exit_delay_end_ms(self) -> float:
        """Return the exit delay end timestamp in milliseconds, or 0."""
        return self._exit_delay_end_ms

    @staticmethod
    def _is_rate_limit_error(exc: UpdateFailed) -> bool:
        """Check if an UpdateFailed wraps a rate-limit error."""
        return isinstance(exc.__cause__, YaleRateLimitError)

    async def _fetch_alarm_devices(
        self, alarm_id: str, alarm_info: dict[str, Any],
    ) -> tuple[str, AlarmData]:
        """Fetch devices for a single alarm and return *(alarm_id, AlarmData)*.

        Builds the ``device_index`` inline so each ``AlarmData`` is
        fully constructed in one place.
        """
        try:
            devices = await self.api.get_alarm_devices(alarm_id)
        except YaleAuthenticationError:
            raise
        except (YaleError, aiohttp.ClientError):
            _LOGGER.warning(
                "Failed to fetch devices for alarm %s — "
                "they will appear on the next successful poll",
                alarm_id,
            )
            devices = []
        skipped = [d for d in devices if "_id" not in d]
        if skipped:
            _LOGGER.warning(
                "Alarm %s: %d device(s) skipped — the Yale API returned devices without an ID",
                alarm_id,
                len(skipped),
            )
        return alarm_id, {
            "info": alarm_info,
            "device_index": {d["_id"]: d for d in devices if "_id" in d},
        }

    async def _fetch_lock_data(
        self, lock_id: str,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """Fetch status and details for a single lock.

        Errors propagate to ``_async_process_lock_results`` via
        ``asyncio.gather(return_exceptions=True)``.
        """
        status, details = await asyncio.gather(
            self.api.get_lock_status(lock_id),
            self.api.get_lock_details(lock_id),
        )
        return lock_id, status, details

    async def _async_ensure_authenticated(self) -> None:
        """Authenticate with the Yale API if no token is present.

        Raises ConfigEntryAuthFailed on auth failure or MFA requirement,
        and UpdateFailed on connection errors.
        """
        if self.api.access_token:
            return
        try:
            authenticated = await self.api.authenticate()
            if not authenticated:
                async_create_auth_issue(self.hass)
                msg = "Authentication requires MFA — reconfigure the integration"
                raise ConfigEntryAuthFailed(msg)
        except YaleAuthenticationError as err:
            async_create_auth_issue(self.hass)
            msg = f"Authentication failed: {err}"
            raise ConfigEntryAuthFailed(msg) from err
        except YaleError as err:
            msg = f"Connection error during authentication: {err}"
            raise UpdateFailed(msg) from err

    async def _async_api_call_with_error_mapping(
        self,
        api_call: Callable[[], Coroutine[Any, Any, _T]],
        label: str,
    ) -> _T:
        """Execute an API call with standard error-to-HA-exception mapping.

        Maps:
            YaleAuthenticationError → ConfigEntryAuthFailed (+ repair issue)
            YaleRateLimitError → UpdateFailed(retry_after=N) (+ repair issue)
            YaleError → UpdateFailed
            aiohttp.ClientError → UpdateFailed
        """
        try:
            return await api_call()
        except YaleAuthenticationError as err:
            async_create_auth_issue(self.hass)
            msg = f"Authentication failed {label}: {err}"
            raise ConfigEntryAuthFailed(msg) from err
        except YaleRateLimitError as err:
            async_create_rate_limit_issue(self.hass)
            msg = f"Rate limited {label}: {err}"
            raise UpdateFailed(msg, retry_after=err.retry_after_seconds) from err
        except YaleError as err:
            msg = f"Error {label}: {err}"
            raise UpdateFailed(msg) from err
        except aiohttp.ClientError as err:
            msg = f"Connection error {label}: {err}"
            raise UpdateFailed(msg) from err

    async def _async_fetch_alarms(self) -> list[dict[str, Any]]:
        """Fetch the alarm list from the API.

        Raises ConfigEntryAuthFailed, UpdateFailed on errors.
        """
        return await self._async_api_call_with_error_mapping(
            self.api.get_alarms, "fetching alarms",
        )

    async def _async_process_alarm_results(
        self,
        alarms: list[dict[str, Any]],
        data: YaleCoordinatorData,
    ) -> None:
        """Fetch devices for each alarm in parallel and populate *data*."""
        valid_alarms = [(str(a["alarmID"]), a) for a in alarms if a.get("alarmID")]
        alarm_results: list[tuple[str, AlarmData] | BaseException] = (
            await asyncio.gather(
                *(self._fetch_alarm_devices(aid, info) for aid, info in valid_alarms),
                return_exceptions=True,
            )
        )
        for result in alarm_results:
            if isinstance(result, YaleAuthenticationError):
                async_create_auth_issue(self.hass)
                msg = f"Authentication failed fetching devices: {result}"
                raise ConfigEntryAuthFailed(msg) from result
            if isinstance(result, BaseException):
                _LOGGER.warning(
                    "Unexpected error while fetching alarm devices — "
                    "some devices may be temporarily missing",
                )
                continue
            alarm_id, alarm_data_item = result
            data["alarms"][alarm_id] = alarm_data_item

    async def _async_fetch_locks(self, data: YaleCoordinatorData) -> None:
        """Fetch the lock list and populate *data['locks']*.

        Type validation is handled by ``get_locks()`` → ``_expect_dict()``,
        which raises ``YaleApiError`` on non-dict responses.  That error is
        mapped to ``UpdateFailed`` by ``_async_api_call_with_error_mapping``.
        """
        data["locks"] = await self._async_api_call_with_error_mapping(
            self.api.get_locks, "fetching locks",
        )

    async def _async_process_lock_results(
        self, data: YaleCoordinatorData,
    ) -> None:
        """Fetch status/details for each lock in parallel and populate *data*.

        Individual lock failures are isolated — a single problematic lock
        does not prevent other locks or alarms from loading.  Auth errors
        always propagate (they affect all endpoints).
        """
        lock_ids = list(data["locks"])
        if not lock_ids:
            return
        lock_results: list[
            tuple[str, dict[str, Any], dict[str, Any]] | BaseException
        ] = await asyncio.gather(
            *(self._fetch_lock_data(lock_id) for lock_id in lock_ids),
            return_exceptions=True,
        )
        for lock_id, result in zip(lock_ids, lock_results, strict=True):
            if isinstance(result, YaleAuthenticationError):
                async_create_auth_issue(self.hass)
                msg = f"Authentication failed fetching lock data: {result}"
                raise ConfigEntryAuthFailed(msg) from result
            if isinstance(result, (YaleError, aiohttp.ClientError)):
                _LOGGER.warning("Failed to fetch data for lock %s — it will update on the next poll", lock_id)
                continue
            if isinstance(result, BaseException):
                _LOGGER.warning("Unexpected error while fetching lock %s — it will update on the next poll", lock_id)
                continue
            _, status, details = result
            data["lock_status"][lock_id] = status
            data["lock_details"][lock_id] = details

    async def _async_fetch_doorbells(self, data: YaleCoordinatorData) -> None:
        """Fetch doorbells and populate *data['doorbells']*.

        Errors are isolated — a doorbell failure must not prevent
        alarms or locks from loading.
        """
        try:
            raw = await self.api.get_doorbells()
            data["doorbells"] = {
                db_id: db
                for db in raw
                if (db_id := db.get("_id") or db.get("doorbellID"))
            }
        except YaleAuthenticationError:
            raise
        except (YaleError, aiohttp.ClientError):
            _LOGGER.warning(
                "Failed to fetch doorbells — "
                "they will appear on the next successful poll",
            )

    def _cleanup_stale_devices(self, data: YaleCoordinatorData) -> None:
        """Remove devices from the registry that are no longer in the API."""
        current_device_ids: set[str] = set()
        for alarm_id, alarm_data_item in data["alarms"].items():
            current_device_ids.add(alarm_id)
            current_device_ids.update(alarm_data_item["device_index"])
        current_device_ids.update(data["locks"])
        current_device_ids.update(data["doorbells"])

        if self.previous_device_ids:
            stale_ids = self.previous_device_ids - current_device_ids
            if stale_ids:
                device_registry = dr.async_get(self.hass)
                for stale_id in stale_ids:
                    device = device_registry.async_get_device(
                        identifiers={(DOMAIN, stale_id)},
                    )
                    if device:
                        _LOGGER.info(
                            "Removing stale device %s (%s)",
                            device.name,
                            stale_id,
                        )
                        device_registry.async_update_device(
                            device_id=device.id,
                            remove_config_entry_id=self.config_entry.entry_id,
                        )
        self.previous_device_ids = current_device_ids

    def _has_degraded_status(self, data: YaleCoordinatorData) -> bool:
        """Check if any entity has a degraded/transient status.

        Currently checks lock ``"unknown"`` status, which indicates the
        Yale cloud cannot determine the lock's state via BLE bridge.
        """
        return any(
            s.get("status") == "unknown" for s in data["lock_status"].values()
        )

    @callback
    def _fire_degraded_repoll(self, _now: Any = None) -> None:
        """Fire a single re-poll after degraded status detection."""
        self.hass.async_create_task(self.async_request_refresh())

    async def _async_fetch_all_data(self) -> YaleCoordinatorData:
        """Fetch all data from the Yale API (no retry logic).

        Fetches alarms and locks in parallel (step 1), then processes
        alarm devices, lock details, and doorbells in parallel (step 2).

        Raises ConfigEntryAuthFailed for auth errors,
        UpdateFailed for transient/rate-limit errors.
        """
        await self._async_ensure_authenticated()

        data: YaleCoordinatorData = {
            "alarms": {},
            "locks": {},
            "lock_status": {},
            "lock_details": {},
            "doorbells": {},
        }

        # Step 1: fetch alarm list + lock list in parallel
        alarms, _ = await asyncio.gather(
            self._async_fetch_alarms(),
            self._async_fetch_locks(data),
        )

        # Step 2: process alarm devices, lock details, and doorbells in parallel
        # (each writes to separate keys in data — no race conditions)
        await asyncio.gather(
            self._async_process_alarm_results(alarms, data),
            self._async_process_lock_results(data),
            self._async_fetch_doorbells(data),
        )
        return data

    async def _async_update_data(self) -> YaleCoordinatorData:
        """Fetch data from the Yale API with retry for transient errors.

        Two-layer retry design:
            Layer 1 (API client ``_request()``): retries transport-level
            errors — HTTP 403 (CDN/WAF), ``ClientConnectionError``, and
            ``TimeoutError``.  Up to ``_MAX_HTTP_403_RETRIES`` /
            ``_MAX_NETWORK_RETRIES`` attempts.

            Layer 2 (this method): retries application-level
            ``UpdateFailed`` errors that survive Layer 1.  Up to
            ``_RETRY_ATTEMPTS`` attempts with exponential backoff +
            jitter.

        The two layers have different scopes and are not redundant.
        Worst-case total attempts = Layer 1 x Layer 2.

        Auth errors (``ConfigEntryAuthFailed``) and rate-limit errors
        (``UpdateFailed`` wrapping ``YaleRateLimitError``) are never
        retried — they propagate immediately.
        """
        last_exc: UpdateFailed | None = None

        for attempt in range(_RETRY_ATTEMPTS):
            try:
                data = await self._async_fetch_all_data()
            except ConfigEntryAuthFailed:
                raise
            except UpdateFailed as exc:
                if self._is_rate_limit_error(exc):
                    raise
                last_exc = exc
                max_delay = min(
                    _RETRY_BASE_DELAY * (_RETRY_BACKOFF_FACTOR ** attempt),
                    _RETRY_MAX_DELAY,
                )
                delay = random.uniform(0, max_delay)
                _LOGGER.warning(
                    "Yale API temporarily unavailable (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    _RETRY_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            # Success — clear repair issues and do post-processing
            async_delete_auth_issue(self.hass)
            async_delete_rate_limit_issue(self.hass)
            self._cleanup_stale_devices(data)

            # Schedule one optimistic re-poll if degraded status detected
            has_degraded = self._has_degraded_status(data)
            if has_degraded and not self._degraded_repoll_scheduled:
                self._degraded_repoll_scheduled = True
                async_call_later(
                    self.hass,
                    _DEGRADED_REPOLL_DELAY,
                    self._fire_degraded_repoll,
                )
                _LOGGER.debug(
                    "Degraded status detected, scheduling re-poll in %ds",
                    _DEGRADED_REPOLL_DELAY,
                )
            if not has_degraded:
                self._degraded_repoll_scheduled = False

            return data

        # All retries exhausted
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------
    # Action methods — entities delegate here instead of calling api directly
    # ------------------------------------------------------------------

    async def async_disarm(self, alarm_id: str, area_ids: list[str]) -> None:
        """Disarm the alarm and refresh."""
        await self.api.disarm(alarm_id, area_ids)
        self._exit_delay_end_ms = 0
        await self._safe_refresh("disarm")

    async def async_arm_home(self, alarm_id: str, area_ids: list[str]) -> None:
        """Arm the alarm in home mode and refresh."""
        result = await self.api.arm_home(alarm_id, area_ids)
        self._exit_delay_end_ms = result.get("exitTime", 0) or 0
        await self._safe_refresh("arm home")

    async def async_arm_away(self, alarm_id: str, area_ids: list[str]) -> None:
        """Arm the alarm in away mode and refresh."""
        result = await self.api.arm_away(alarm_id, area_ids)
        self._exit_delay_end_ms = result.get("exitTime", 0) or 0
        await self._safe_refresh("arm away")

    async def async_lock(self, lock_id: str) -> None:
        """Lock a door and refresh."""
        await self.api.lock(lock_id)
        await self._safe_refresh("lock")

    async def async_unlock(self, lock_id: str) -> None:
        """Unlock a door and refresh."""
        await self.api.unlock(lock_id)
        await self._safe_refresh("unlock")

    async def async_update_alarm_settings(
        self,
        alarm_id: str,
        settings: dict[str, Any],
    ) -> None:
        """Update alarm-level settings and refresh."""
        await self.api.update_alarm_settings(alarm_id, settings)
        await self._safe_refresh("update alarm settings")

    async def async_update_device(
        self,
        alarm_id: str,
        device_id: str,
        settings: dict[str, Any],
    ) -> None:
        """Update per-device settings and refresh."""
        await self.api.update_device(alarm_id, device_id, settings)
        await self._safe_refresh("update device settings")

    async def _safe_refresh(self, action: str) -> None:
        """Request a coordinator refresh, logging but not raising on failure.

        The action itself already succeeded — a refresh failure should
        not be reported as an action failure to the user.
        """
        try:
            await self.async_request_refresh()
        except Exception:  # noqa: BLE001 — refresh failure must not mask a successful action
            _LOGGER.warning(
                "Command '%s' succeeded but the status refresh failed — "
                "the dashboard will update on the next poll cycle",
                action,
            )
