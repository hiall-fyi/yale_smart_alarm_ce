"""Constants for Yale Smart Alarm CE integration."""
from __future__ import annotations

DOMAIN = "yale_smart_alarm_ce"
MANUFACTURER = "Yale"

# API endpoints
API_BASE_URL = "https://api.aaecosystem.com"
API_AUTH_URL = "https://api.aaecosystem.com/v2"

# Auth endpoints (use API_AUTH_URL)
API_SIGNIN = "/session/signin"
API_SEND_CODE = "/validation/email"
API_VALIDATE_EMAIL = "/validate/email"

# Data endpoints (use API_BASE_URL)
API_ALARMS = "/users/alarms/mine"
API_LOCKS = "/users/locks/mine"
API_DOORBELLS = "/users/doorbells/mine"

# Alarm states (from API response)
ARM_STATE_DISARM = "ARM_STATE_UNSET"
ARM_STATE_PARTIAL = "ARM_STATE_PART_ARM"
ARM_STATE_FULL = "ARM_STATE_ARMED"

# Alarm state commands (for PUT request)
CMD_DISARM = "DISARM"
CMD_PARTIAL_ARM = "PARTIAL_ARM"
CMD_FULL_ARM = "FULL_ARM"

# Device types
DEVICE_TYPE_KEYPAD = "alarm_keypad"
DEVICE_TYPE_CONTACT_INDOOR = "alarm_contact_indoor"
DEVICE_TYPE_CONTACT_OUTDOOR = "alarm_contact_outdoor"
DEVICE_TYPE_MOTION_INDOOR = "alarm_pir_indoor"
DEVICE_TYPE_MOTION_OUTDOOR = "alarm_pir_outdoor"
DEVICE_TYPE_SHOCK = "alarm_shock_sensor"
DEVICE_TYPE_SIREN_INDOOR = "alarm_siren_indoor"
DEVICE_TYPE_SIREN_OUTDOOR = "alarm_siren_outdoor"
DEVICE_TYPE_KEYFOB = "alarm_keyfob"
DEVICE_TYPE_SMOKE = "alarm_smoke_sensor"
DEVICE_TYPE_RF_BUTTON = "alarm_rf_button"

# Device type groups — frozenset for O(1) membership checks
CONTACT_SENSOR_TYPES: frozenset[str] = frozenset({
    DEVICE_TYPE_CONTACT_INDOOR,
    DEVICE_TYPE_CONTACT_OUTDOOR,
    DEVICE_TYPE_SHOCK,
})
MOTION_SENSOR_TYPES: frozenset[str] = frozenset({
    DEVICE_TYPE_MOTION_INDOOR,
    DEVICE_TYPE_MOTION_OUTDOOR,
})
SIREN_TYPES: frozenset[str] = frozenset({
    DEVICE_TYPE_SIREN_INDOOR, DEVICE_TYPE_SIREN_OUTDOOR,
})

# Device type to friendly name mapping
DEVICE_TYPE_NAMES: dict[str, str] = {
    DEVICE_TYPE_KEYPAD: "Keypad",
    DEVICE_TYPE_CONTACT_INDOOR: "Door/Window Sensor",
    DEVICE_TYPE_CONTACT_OUTDOOR: "Outdoor Contact Sensor",
    DEVICE_TYPE_MOTION_INDOOR: "Motion Sensor",
    DEVICE_TYPE_MOTION_OUTDOOR: "Outdoor Motion Sensor",
    DEVICE_TYPE_SHOCK: "Shock Sensor",
    DEVICE_TYPE_SIREN_INDOOR: "Indoor Siren",
    DEVICE_TYPE_SIREN_OUTDOOR: "Outdoor Siren",
    DEVICE_TYPE_KEYFOB: "Keyfob",
    DEVICE_TYPE_SMOKE: "Smoke Sensor",
    DEVICE_TYPE_RF_BUTTON: "Panic Button",
}

# API Key (decrypted from Yale Home app)
# Different regions use different API keys
YALE_API_KEYS: dict[str, str] = {
    "global": "2fcb39a8-40b1-4f4e-bc58-1aeecc0670e0",  # Yale Global (EU, UK, US, etc.)
    "china": "27a62540-8baf-4851-b1fb-0fa40d49429d",   # Yale China
    "gateman": "3496ae4f-c5d7-4283-a8cd-1eee77078db8", # Gateman (Korea)
    "lockwood": "1c953333-0924-4506-9f94-6f122ee7d105", # Lockwood (Australia/NZ)
}

# Default API key (Global)
YALE_API_KEY = YALE_API_KEYS["global"]

CONF_API_KEY = "api_key"
CONF_REGION = "region"
CONF_INSTALL_ID = "install_id"
CONF_UPDATE_INTERVAL = "update_interval"

# Default update interval
DEFAULT_UPDATE_INTERVAL = 30  # seconds
MIN_UPDATE_INTERVAL = 10
MAX_UPDATE_INTERVAL = 300

# Region options for config flow
REGION_OPTIONS: dict[str, str] = {
    "global": "Yale Global (EU, UK, US)",
    "china": "Yale China (中國)",
    "gateman": "Gateman (Korea/한국)",
    "lockwood": "Lockwood (Australia/NZ)",
}

# Volume options for select entities
VOLUME_OPTIONS: list[str] = ["OFF", "LOW", "MID", "HIGH"]

# User-Agent string for API requests (from Yale Home app)
USER_AGENT = "Yale/2025.13.0 (Android 14)"
