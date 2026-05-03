"""Yale Smart Alarm CE API client."""
from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from collections.abc import Mapping

from .const import (
    API_ALARMS,
    API_AUTH_URL,
    API_BASE_URL,
    API_DOORBELLS,
    API_LOCKS,
    API_SEND_CODE,
    API_SIGNIN,
    API_VALIDATE_EMAIL,
    CMD_DISARM,
    CMD_FULL_ARM,
    CMD_PARTIAL_ARM,
    USER_AGENT,
    YALE_API_KEY,
    YALE_API_KEYS,
)
from .error_handler import (
    YaleApiError,
    YaleAuthenticationError,
    YaleConnectionError,
    YaleRateLimitError,
)

_LOGGER = logging.getLogger(__name__)

# Default timeout for all API requests (seconds)
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# HTTP status codes used in response handling
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_HTTP_PRECONDITION_FAILED = 412
_HTTP_TOO_MANY_REQUESTS = 429

# 403 retry configuration — transient CDN/WAF blocks
_MAX_HTTP_403_RETRIES = 3
_HTTP_403_RETRY_BASE_DELAY = 2

# Network retry configuration — transient connection errors
_MAX_NETWORK_RETRIES = 3
_NETWORK_RETRY_BASE_DELAY = 2  # seconds — exponential: 2s, 4s, 8s
_NETWORK_RETRY_MAX_DELAY = 30  # seconds — cap to prevent runaway delays

# Rate limit (HTTP 429) Retry-After sanitization
_RATE_LIMIT_MIN_S = 10      # minimum wait
_RATE_LIMIT_MAX_S = 300     # maximum wait (5 minutes)
_RATE_LIMIT_DEFAULT_S = 60  # default when header is absent or unparseable


def _parse_retry_after_header(header: str | None) -> float | None:
    """Parse HTTP Retry-After header (seconds or HTTP-date).

    Returns the number of seconds to wait, or None if the header is
    absent or malformed.
    """
    if header is None:
        return None
    # Try seconds format first
    try:
        return float(header)
    except ValueError:
        pass
    # Try HTTP-date format
    try:
        parsed = email.utils.parsedate_to_datetime(header)
        now = datetime.now(tz=UTC)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (parsed - now).total_seconds())
    except (ValueError, TypeError):
        return None


def _sanitize_retry_after(value: float | None) -> int:
    """Clamp a retry-after value to a safe range.

    Returns ``_RATE_LIMIT_DEFAULT_S`` when *value* is None or ≤ 0.
    """
    if value is None or value <= 0:
        return _RATE_LIMIT_DEFAULT_S
    return int(min(max(value, _RATE_LIMIT_MIN_S), _RATE_LIMIT_MAX_S))


class YaleApiClient:
    """Handle communication with the Yale / AA Ecosystem REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        api_key: str | None = None,
        region: str | None = None,
        install_id: str | None = None,
    ) -> None:
        """Initialize the YaleApiClient."""
        self._session = session
        self.email = email
        self.password = password
        self.access_token: str | None = None
        self.step_token: str | None = None
        self.install_id: str = install_id or str(uuid.uuid4())

        if api_key:
            self.api_key = api_key
        elif region and region in YALE_API_KEYS:
            self.api_key = YALE_API_KEYS[region]
        else:
            self.api_key = YALE_API_KEY

    def _get_headers(self, *, include_token: bool = True) -> dict[str, str]:
        """Build common request headers."""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        }
        if include_token and self.access_token:
            headers["x-access-token"] = self.access_token
        return headers

    async def _check_response_status(
        self,
        resp: aiohttp.ClientResponse,
    ) -> tuple[Any, Mapping[str, str]]:
        """Validate response status and return parsed JSON body + headers.

        Handles 401 (auth error) and 429 (rate limit) immediately.
        For 2xx, parses JSON and returns ``(body, headers)``.
        For other non-2xx, raises ``YaleApiError``.
        """
        if resp.status == _HTTP_UNAUTHORIZED:
            body = await resp.text()
            msg = f"Authentication failed (HTTP {resp.status}): {body}"
            raise YaleAuthenticationError(msg)

        if resp.status == _HTTP_TOO_MANY_REQUESTS:
            raw_header = resp.headers.get("Retry-After")
            parsed = _parse_retry_after_header(raw_header)
            seconds = _sanitize_retry_after(parsed)
            _LOGGER.info("Rate limited (HTTP 429), deferring refresh %ds", seconds)
            msg = f"Rate limit exceeded (HTTP 429), retry after {seconds}s"
            raise YaleRateLimitError(msg, retry_after_seconds=seconds)

        if resp.status == _HTTP_PRECONDITION_FAILED:
            body = await resp.text()
            _LOGGER.warning(
                "Precondition failed (HTTP 412): %s",
                body[:200],
            )
            msg = "The alarm must be disarmed before changing settings"
            raise YaleApiError(msg)

        try:
            resp.raise_for_status()
        except aiohttp.ClientResponseError as err:
            msg = f"API error (HTTP {err.status}): {err.message}"
            raise YaleApiError(msg) from err

        json_body = await resp.json(content_type=None)
        return json_body, resp.headers

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        use_auth_url: bool = False,
        include_token: bool = True,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> tuple[Any, Mapping[str, str]]:
        """Execute an API request with retry for transient errors.

        Retries on:
        - HTTP 403 (transient CDN/WAF blocks) — clears tokens, rebuilds headers.
        - Network errors (``ClientConnectionError``, ``TimeoutError``) — for
          idempotent methods (GET/PUT/DELETE).  POST only retries connection
          errors (not timeouts) because the server may have received the request.

        Never retries:
        - HTTP 401 (``YaleAuthenticationError``) — propagates immediately.
        - HTTP 429 (``YaleRateLimitError``) — propagates immediately.
        - Parse errors (``ContentTypeError``, ``ValueError``) — not transient.

        Raises:
            YaleAuthenticationError: On HTTP 401, or 403 after retries exhausted.
            YaleRateLimitError: On HTTP 429.
            YaleApiError: On other non-2xx HTTP responses.
            YaleConnectionError: On connection failures after retries exhausted.

        """
        base_url = API_AUTH_URL if use_auth_url else API_BASE_URL
        url = f"{base_url}{endpoint}"
        req_headers = headers or self._get_headers(include_token=include_token)
        max_attempts = max(_MAX_HTTP_403_RETRIES, _MAX_NETWORK_RETRIES)
        last_conn_err: YaleConnectionError | None = None

        for attempt in range(max_attempts):
            try:
                async with self._session.request(
                    method, url, headers=req_headers, json=json, timeout=_REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status == _HTTP_FORBIDDEN:
                        if attempt < _MAX_HTTP_403_RETRIES - 1:
                            delay = random.uniform(0, _HTTP_403_RETRY_BASE_DELAY ** (attempt + 1))
                            _LOGGER.warning(
                                "Yale API returned 403 on %s (attempt %d/%d) — retrying in %.1fs",
                                endpoint,
                                attempt + 1,
                                _MAX_HTTP_403_RETRIES,
                                delay,
                            )
                            if not use_auth_url:
                                # Yale API 403s are typically transient CDN/WAF
                                # blocks, not permission errors.  Clearing tokens
                                # forces a fresh auth on the next coordinator
                                # cycle if the 403 persists past all retries.
                                # Trade-off: a genuine permission 403 would also
                                # clear tokens, but it exhausts retries and
                                # raises YaleAuthenticationError regardless.
                                self.access_token = None
                                self.step_token = None
                            await asyncio.sleep(delay)
                            # Rebuild headers with (possibly cleared) token
                            req_headers = headers or self._get_headers(
                                include_token=include_token,
                            )
                            continue
                        # All 403 retries exhausted
                        body = await resp.text()
                        msg = (
                            f"Authentication failed (HTTP {resp.status}) "
                            f"after {_MAX_HTTP_403_RETRIES} attempts: {body}"
                        )
                        raise YaleAuthenticationError(msg)

                    return await self._check_response_status(resp)
            except (YaleAuthenticationError, YaleRateLimitError, YaleApiError):
                raise  # never retry auth, rate-limit, or API errors
            except (aiohttp.ClientConnectionError, TimeoutError) as err:
                # POST + timeout → server may have received the request
                if method == "POST" and isinstance(err, TimeoutError):
                    msg = f"Connection timeout on POST {endpoint}: {err}"
                    raise YaleConnectionError(msg) from err
                last_conn_err = YaleConnectionError(f"Connection error: {err}")
                last_conn_err.__cause__ = err
                if attempt < max_attempts - 1:
                    delay = random.uniform(
                        0,
                        min(_NETWORK_RETRY_MAX_DELAY, _NETWORK_RETRY_BASE_DELAY ** (attempt + 1)),
                    )
                    _LOGGER.warning(
                        "Connection issue on %s %s (attempt %d/%d), retrying in %.1fs",
                        method,
                        endpoint,
                        attempt + 1,
                        max_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise last_conn_err from err
            except aiohttp.ContentTypeError as err:
                msg = f"Unexpected response content type: {err}"
                raise YaleApiError(msg) from err
            except ValueError as err:
                # json.JSONDecodeError is a subclass of ValueError
                msg = f"Invalid JSON in API response: {err}"
                raise YaleApiError(msg) from err

        # Safety net — should not reach here
        if last_conn_err is not None:
            raise last_conn_err
        msg = f"Request to {endpoint} failed after {max_attempts} attempts"
        raise YaleAuthenticationError(msg)

    # ------------------------------------------------------------------
    # Authentication flow
    # ------------------------------------------------------------------

    async def authenticate_step1(self) -> dict[str, Any]:
        """Perform step 1: initial sign-in, returning MFA options."""
        data = {
            "identifierType": "email",
            "identifier": self.email,
            "credential": self.password,
            "installID": self.install_id,
        }
        result, headers = await self._request(
            "POST", API_SIGNIN, use_auth_url=True, include_token=False, json=data,
        )
        self.step_token = headers.get("x-step-token")
        # Some accounts skip MFA — the access token arrives directly in step1
        access = headers.get("x-access-token")
        if access:
            self.access_token = access
        if not isinstance(result, dict):
            msg = f"Expected dict from signin, got {type(result).__name__}"
            raise YaleApiError(msg)
        return result

    async def authenticate_step2_send_code(self) -> bool:
        """Perform step 2: request a verification code via email."""
        if not self.step_token:
            msg = "No step token — call authenticate_step1 first"
            raise ValueError(msg)

        headers = self._get_headers(include_token=False)
        headers["x-step-token"] = self.step_token
        data = {"identifier": self.email}

        _, resp_headers = await self._request(
            "POST", API_SEND_CODE, use_auth_url=True, include_token=False,
            headers=headers, json=data,
        )
        new_token = resp_headers.get("x-step-token")
        if new_token:
            self.step_token = new_token
        return True

    async def authenticate_step3_validate(self, code: str) -> bool:
        """Perform step 3: validate the verification code and obtain an access token."""
        if not self.step_token:
            msg = "No step token — call authenticate_step1 first"
            raise ValueError(msg)

        headers = self._get_headers(include_token=False)
        headers["x-step-token"] = self.step_token
        data = {"code": code, "identifier": self.email}

        _, resp_headers = await self._request(
            "POST", API_VALIDATE_EMAIL, use_auth_url=True, include_token=False,
            headers=headers, json=data,
        )
        self.access_token = resp_headers.get("x-access-token")
        if not self.access_token:
            msg = "No access token in response"
            raise YaleAuthenticationError(msg)
        return True

    async def authenticate(self, verification_code: str | None = None) -> bool:
        """Run the full authentication flow (convenience wrapper).

        Returns *True* when fully authenticated, *False* when MFA code is needed.
        Raises on unrecoverable errors (network, auth).

        Flow:
            1. No step_token → call step1 (sign-in).
               - If MFA required → send code email, return False.
               - If no MFA → step1 grants token directly, return True.
            2. Have step_token + verification_code → validate code, return True.
            3. Have step_token but no code → caller must provide code, return False.
        """
        if not self.step_token:
            result = await self.authenticate_step1()
            if result.get("needVerify"):
                await self.authenticate_step2_send_code()
                return False  # Caller must re-call with verification_code
            # No MFA required — step1 granted access_token via response headers
            if self.access_token:
                return True

        if verification_code:
            await self.authenticate_step3_validate(verification_code)
            return True

        # step_token exists but no code provided — waiting for MFA input
        return False

    # ------------------------------------------------------------------
    # Response validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _expect_list(result: Any, endpoint: str) -> list[dict[str, Any]]:
        """Validate that *result* is a list and return it."""
        if not isinstance(result, list):
            msg = f"Expected list from {endpoint}, got {type(result).__name__}"
            raise YaleApiError(msg)
        return result

    @staticmethod
    def _expect_dict(result: Any, endpoint: str) -> dict[str, Any]:
        """Validate that *result* is a dict and return it."""
        if not isinstance(result, dict):
            msg = f"Expected dict from {endpoint}, got {type(result).__name__}"
            raise YaleApiError(msg)
        return result

    # ------------------------------------------------------------------
    # Alarm endpoints
    # ------------------------------------------------------------------

    async def get_alarms(self) -> list[dict[str, Any]]:
        """Fetch all alarms for the authenticated user."""
        result, _ = await self._request("GET", API_ALARMS)
        return self._expect_list(result, API_ALARMS)


    async def get_alarm_devices(self, alarm_id: str) -> list[dict[str, Any]]:
        """Fetch devices belonging to an alarm."""
        endpoint = f"/alarms/{alarm_id}/devices"
        result, _ = await self._request("GET", endpoint)
        return self._expect_list(result, endpoint)

    async def set_alarm_state(
        self, alarm_id: str, state: str, area_ids: list[str],
    ) -> dict[str, Any]:
        """Set the arm state for specific areas."""
        endpoint = f"/alarms/{alarm_id}/state/{state}"
        data = {"areaIDs": area_ids}
        result, _ = await self._request("PUT", endpoint, json=data)
        return self._expect_dict(result, endpoint)

    async def disarm(self, alarm_id: str, area_ids: list[str]) -> dict[str, Any]:
        """Disarm the alarm."""
        return await self.set_alarm_state(alarm_id, CMD_DISARM, area_ids)

    async def arm_home(self, alarm_id: str, area_ids: list[str]) -> dict[str, Any]:
        """Arm the alarm in home mode (partial)."""
        return await self.set_alarm_state(alarm_id, CMD_PARTIAL_ARM, area_ids)

    async def arm_away(self, alarm_id: str, area_ids: list[str]) -> dict[str, Any]:
        """Arm the alarm in away mode (full)."""
        return await self.set_alarm_state(alarm_id, CMD_FULL_ARM, area_ids)


    async def update_alarm_settings(
        self,
        alarm_id: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Update alarm-level settings (alarm must be disarmed)."""
        endpoint = f"/alarms/{alarm_id}"
        result, _ = await self._request("PUT", endpoint, json=settings)
        return self._expect_dict(result, endpoint)

    async def update_device(
        self,
        alarm_id: str,
        device_id: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Update per-device settings (must include 'type' field)."""
        endpoint = f"/alarms/{alarm_id}/devices/{device_id}"
        result, _ = await self._request("PUT", endpoint, json=settings)
        return self._expect_dict(result, endpoint)

    # ------------------------------------------------------------------
    # Lock endpoints
    # ------------------------------------------------------------------

    async def get_locks(self) -> dict[str, Any]:
        """Fetch all locks."""
        result, _ = await self._request("GET", API_LOCKS)
        return self._expect_dict(result, API_LOCKS)


    async def get_doorbells(self) -> list[dict[str, Any]]:
        """Fetch all doorbells for the authenticated user.

        Yale API returns a JSON array for users with doorbells, but a
        dict (e.g. ``{}``) for users without any.  The official Yale
        Home app catches the resulting parse error and treats it as
        "no doorbells".  We replicate that behaviour here.
        """
        result, _ = await self._request("GET", API_DOORBELLS)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # Yale API returns {} or similar dict for users without doorbells.
            _LOGGER.debug("Doorbells endpoint returned dict (no doorbells): %s", list(result.keys()))
            return []
        msg = f"Expected list or dict from {API_DOORBELLS}, got {type(result).__name__}"
        raise YaleApiError(msg)

    async def get_lock_status(self, lock_id: str) -> dict[str, Any]:
        """Fetch the current status of a lock."""
        endpoint = f"/locks/{lock_id}/status"
        result, _ = await self._request("GET", endpoint)
        return self._expect_dict(result, endpoint)

    async def get_lock_details(self, lock_id: str) -> dict[str, Any]:
        """Fetch detailed information for a lock."""
        endpoint = f"/locks/{lock_id}"
        result, _ = await self._request("GET", endpoint)
        return self._expect_dict(result, endpoint)

    async def lock(self, lock_id: str) -> dict[str, Any]:
        """Lock the door."""
        endpoint = f"/remoteoperate/{lock_id}/lock"
        result, _ = await self._request("PUT", endpoint)
        return self._expect_dict(result, endpoint)

    async def unlock(self, lock_id: str) -> dict[str, Any]:
        """Unlock the door."""
        endpoint = f"/remoteoperate/{lock_id}/unlock"
        result, _ = await self._request("PUT", endpoint)
        return self._expect_dict(result, endpoint)
