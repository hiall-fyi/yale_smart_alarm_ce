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
                    "Authentication error during %s - token may have expired",
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
            except YaleError as err:
                _LOGGER.exception("Yale error during %s", operation)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="api_error",
                    translation_placeholders={
                        "operation": operation,
                        "error": str(err),
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
                        "error": str(err),
                    },
                ) from err

        return wrapper  # type: ignore[return-value]

    return decorator
