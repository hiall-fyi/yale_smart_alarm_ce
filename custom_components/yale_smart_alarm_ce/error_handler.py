"""Error handling utilities for Yale Smart Alarm CE integration."""
from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

_LOGGER = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class YaleError(HomeAssistantError):
    """Base exception for Yale Smart Alarm CE errors."""


class YaleApiError(YaleError):
    """Represent a non-2xx API response error."""


class YaleArmConflictError(YaleApiError):
    """Represent an HTTP 409 arm conflict with open/faulted sensors."""

    def __init__(
        self,
        msg: str,
        *,
        inhibit_errors: list[dict[str, str]],
    ) -> None:
        """Initialize with inhibit error details.

        Each entry in inhibit_errors has 'device_id' and 'code'.
        """
        super().__init__(msg)
        self.inhibit_errors = inhibit_errors


class YaleRateLimitError(YaleError):
    """Represent a rate-limit (HTTP 429) error."""

    def __init__(self, msg: str, *, retry_after_seconds: int | None = None) -> None:
        """Initialize with optional retry-after duration in seconds."""
        super().__init__(msg)
        self.retry_after_seconds = retry_after_seconds


class YaleAuthenticationError(YaleError):
    """Represent an authentication (HTTP 401/403) error."""


class YaleConnectionError(YaleError):
    """Represent a connection error."""


def async_handle_errors(
    operation: str,
) -> Callable[
    [Callable[Concatenate[Any, P], Coroutine[Any, Any, T | None]]],
    Callable[Concatenate[Any, P], Coroutine[Any, Any, T | None]],
]:
    """Decorate an async entity method with standardised error handling.

    Logs the error and re-raises as HomeAssistantError so the UI shows
    a meaningful error toast to the user.
    """

    def decorator(
        func: Callable[Concatenate[Any, P], Coroutine[Any, Any, T | None]],
    ) -> Callable[Concatenate[Any, P], Coroutine[Any, Any, T | None]]:
        """Wrap *func* with error handling."""

        @functools.wraps(func)
        async def wrapper(
            self: Any,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> T | None:
            try:
                return await func(self, *args, **kwargs)
            except YaleAuthenticationError:
                _LOGGER.error(
                    "Authentication error during %s — token may have expired",
                    operation,
                )
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="auth_failed",
                ) from None
            except YaleRateLimitError:
                _LOGGER.warning("Rate limit hit during %s", operation)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="rate_limited",
                ) from None
            except YaleArmConflictError as err:
                coordinator = getattr(self, "coordinator", None)
                alarm_id = getattr(self, "_alarm_id", None)
                resolved: list[dict[str, str]] = []
                if coordinator and alarm_id and err.inhibit_errors:
                    resolved = coordinator.resolve_inhibit_errors(
                        alarm_id, err.inhibit_errors,
                    )
                # Fire event for automations
                hass = getattr(self, "hass", None)
                if hass and alarm_id:
                    arm_state_label = operation.replace("arm ", "")
                    hass.bus.async_fire(
                        f"{DOMAIN}_arm_blocked",
                        {
                            "entity_id": getattr(self, "entity_id", ""),
                            "arm_state": arm_state_label,
                            "devices": resolved,
                        },
                    )
                # Raise translated error for UI
                if resolved:
                    sensor_list = ", ".join(
                        f"{d['device_name']} ({d['reason']})" for d in resolved
                    )
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="arm_conflict",
                        translation_placeholders={"sensors": sensor_list},
                    ) from err
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="arm_conflict_unknown",
                ) from err
            except YaleError as err:
                _LOGGER.exception("Yale error during %s", operation)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="api_error",
                    translation_placeholders={
                        "operation": operation,
                        "error": type(err).__name__,
                    },
                ) from err
            except HomeAssistantError:
                raise
            except Exception as err:
                _LOGGER.exception("Failed to %s", operation)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="unexpected_error",
                    translation_placeholders={
                        "operation": operation,
                        "error": type(err).__name__,
                    },
                ) from err

        return wrapper

    return decorator
