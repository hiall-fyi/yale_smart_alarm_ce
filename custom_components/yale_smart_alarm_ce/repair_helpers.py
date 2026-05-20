"""Repairs support for Yale Smart Alarm CE."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

ISSUE_AUTH_EXPIRED = "auth_expired"
ISSUE_RATE_LIMITED = "rate_limited"


def async_create_auth_issue(hass: HomeAssistant) -> None:
    """Create a repair issue for expired authentication."""
    async_create_issue(
        hass,
        DOMAIN,
        ISSUE_AUTH_EXPIRED,
        is_fixable=False,
        severity=IssueSeverity.ERROR,
        translation_key=ISSUE_AUTH_EXPIRED,
    )


def async_delete_auth_issue(hass: HomeAssistant) -> None:
    """Remove the auth expired repair issue."""
    async_delete_issue(hass, DOMAIN, ISSUE_AUTH_EXPIRED)


def async_create_rate_limit_issue(hass: HomeAssistant) -> None:
    """Create a repair issue for rate limiting."""
    async_create_issue(
        hass,
        DOMAIN,
        ISSUE_RATE_LIMITED,
        is_fixable=False,
        severity=IssueSeverity.WARNING,
        translation_key=ISSUE_RATE_LIMITED,
    )


def async_delete_rate_limit_issue(hass: HomeAssistant) -> None:
    """Remove the rate limit repair issue."""
    async_delete_issue(hass, DOMAIN, ISSUE_RATE_LIMITED)
