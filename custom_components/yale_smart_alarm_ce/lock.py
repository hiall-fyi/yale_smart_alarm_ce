"""Yale Smart Lock platform."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import callback

from .entity import YaleLockEntity, setup_dynamic_platform
from .error_handler import async_handle_errors

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import YaleConfigEntry, YaleDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Limit parallel action calls to the Yale cloud API.
PARALLEL_UPDATES = 1

VALID_LOCK_STATES: frozenset[str] = frozenset(
    {"locked", "unlocked", "locking", "unlocking", "jammed"},
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yale lock entities."""

    def _create_entities(
        coordinator: YaleDataUpdateCoordinator, known_keys: set[str],
    ) -> list[YaleLock]:
        """Create entities for all current locks, skipping already-known ones."""
        entities: list[YaleLock] = []
        for lock_id in coordinator.data.get("locks", {}):
            if lock_id not in known_keys:
                known_keys.add(lock_id)
                entities.append(YaleLock(coordinator, lock_id))
        return entities

    setup_dynamic_platform(entry, async_add_entities, _create_entities)


class YaleLock(YaleLockEntity, LockEntity):
    """Represent a Yale smart lock."""

    def __init__(
        self,
        coordinator: YaleDataUpdateCoordinator,
        lock_id: str,
    ) -> None:
        """Initialize the YaleLock."""
        super().__init__(coordinator, lock_id)
        self._attr_unique_id = lock_id
        self._attr_translation_key = "lock"
        # Last known valid locked state — prevents false "unlocked" on API errors
        self._last_known_locked: bool | None = None

    # ------------------------------------------------------------------
    # State tracking — moved out of property to avoid side-effects
    # ------------------------------------------------------------------

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update cached lock state when coordinator refreshes."""
        status = self.lock_status.get("status")
        if status in VALID_LOCK_STATES:
            self._last_known_locked = status == "locked"
        super()._handle_coordinator_update()

    @property
    def _current_status(self) -> str | None:
        """Return the current status string only if it is a known valid value."""
        status: str | None = self.lock_status.get("status")
        if status in VALID_LOCK_STATES:
            return status
        return None

    @property
    def is_locked(self) -> bool | None:
        """Return True if the lock is locked.

        Falls back to the last known state when the API returns an
        invalid or missing status to avoid showing a false "unlocked".
        """
        status = self._current_status
        if status is not None:
            return status == "locked"

        if self._last_known_locked is not None:
            _LOGGER.debug(
                "Lock %s reported unclear status '%s', using last known state (%s)",
                self._lock_id,
                self.lock_status.get("status"),
                "locked" if self._last_known_locked else "unlocked",
            )
            return self._last_known_locked

        _LOGGER.warning(
            "Lock %s reported unclear status '%s' — no previous state available, showing as unknown",
            self._lock_id,
            self.lock_status.get("status"),
        )
        return None

    @property
    def is_locking(self) -> bool:
        """Return True if the lock is currently locking."""
        return self._current_status == "locking"

    @property
    def is_unlocking(self) -> bool:
        """Return True if the lock is currently unlocking."""
        return self._current_status == "unlocking"

    @property
    def is_jammed(self) -> bool:
        """Return True if the lock is jammed."""
        return self._current_status == "jammed"

    @property
    def available(self) -> bool:
        """Return True if the entity has usable state.

        Available whenever the coordinator is healthy and lock status
        data exists — regardless of whether the lock/unlock position
        is known.  An ``"unknown"`` API status keeps the entity
        available; ``is_locked`` handles the uncertainty.
        """
        return super().available and bool(self.lock_status)

    @async_handle_errors("lock door")  # type: ignore[arg-type]
    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock."""
        _LOGGER.debug("Locking %s", self._lock_id)
        await self.coordinator.async_lock(self._lock_id)

    @async_handle_errors("unlock door")  # type: ignore[arg-type]
    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock."""
        _LOGGER.debug("Unlocking %s", self._lock_id)
        await self.coordinator.async_unlock(self._lock_id)
