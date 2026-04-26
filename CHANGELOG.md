# Changelog

All notable changes to Yale Smart Alarm CE are documented here.

---

## 0.1.0 — First Beta Release (2026-04-27)

The first public beta. This build has been running on the developer's own setup for months. Looking for beta testers with different Yale devices — see [#2](https://github.com/hiall-fyi/yale_smart_alarm_ce/issues/2) if you'd like to help.

### What's Included

- **Alarm control** — Arm Home, Arm Away, Disarm with multi-area support
- **Contact sensors** — Door/window open/close detection (indoor, outdoor, shock)
- **Motion sensors** — PIR motion detection (indoor and outdoor)
- **Smart locks** — Lock/unlock with door state, battery level, and jammed detection
- **Battery monitoring** — Low battery alerts for all devices, battery percentage for locks and hub
- **Connectivity** — Online/offline status for every device
- **Tamper detection** — Tamper alerts for the hub and individual devices
- **RF jamming detection** — Alerts when RF interference is detected
- **Smoke sensors** — Smoke detection and fault alerts
- **Panic buttons** — Activation state for RF panic buttons
- **Doorbells** — Doorbell press detection
- **Volume controls** — Siren, chime, and trouble volume (OFF/LOW/MID/HIGH) for the hub and individual sirens
- **Hub settings** — White LED, tamper detection, RF jam detection, force arm, cellular backup, WiFi, daylight savings, RF supervisory, keypad quickset
- **Device settings** — Entry/exit tones (sirens), proximity wakeup (keypads)
- **Multi-region** — Global (EU, UK, US), China, Korea (Gateman), Australia/NZ (Lockwood)
- **MFA authentication** — Email verification code support during setup
- **Reconfigure without removing** — Change your password or region from the integration card
- **Diagnostics** — Download a diagnostics report from the integration card (sensitive data is automatically removed)
- **Repair issues** — Auth expiry and rate limiting show up in Settings → Repairs

### Reliability

- Automatic retry for temporary API errors and network issues
- Yale's CDN occasionally blocks requests — the integration retries up to 3 times before prompting re-authentication
- Rate limit handling — if the Yale API asks you to slow down, the integration backs off automatically (requires HA 2025.11+)
- Lock state preserved during API errors — no false "unlocked" readings
- Automatic re-poll when lock status is uncertain
- Randomised retry timing to avoid overloading the Yale API when multiple Home Assistant instances recover from an outage

### Known Limitations

- **Cloud-only** — All control goes through Yale's cloud servers
- **Temperature sensors removed** — The Yale API returns temperature readings that can be months old with no indication of staleness, so they've been removed entirely
- **Polling only** — No real-time push notifications; the integration polls at your configured interval (default 30 seconds)
- **Untested devices** — Outdoor sensors, smoke sensors, panic buttons, doorbells, and lock models other than Linus L2 are supported in code but haven't been verified with real hardware yet

---

## Pre-release Development

Development history prior to the first beta. These entries are kept for reference but may describe features that were later changed or removed.

### 2026-03-22

- Temporary API errors (timeouts, connection resets) are now retried up to 3 times instead of immediately showing devices as unavailable.

### 2026-03-10

- ~~PubNub real-time updates~~ *(removed)* — Proved unreliable, replaced by polling.
- Fixed doorbell detection for users without doorbells — the Yale API returns a different response format when you don't have any.

### 2026-03-09

- Doorbell support added.
- New sensors: Cellular status, Timezone, Lock battery state.
- New binary sensors: Ethernet, Test mode, Supports entry codes.
- Bluetooth MAC address on lock devices.

### 2026-03-06 – 2026-03-08

- Multi-region support.
- Reconfigure flow (change password/region without removing the integration).
- Diagnostics support with automatic removal of sensitive data.
- Repair issues for auth expiry and rate limiting.
- Each physical device now appears as a separate device in Home Assistant.
- Icons for all controls and sensors.
- English translations for the setup flow and all device names.

### 2026-02-02

- Reduced log noise — only warnings and errors at default level.

### 2026-01-29

- Lock state preserved during API errors to prevent false "unlocked" readings.

### 2026-01-26

- Initial development — alarm control, contact sensors, motion sensors, smart locks, battery monitoring, connectivity, tamper detection, RF jamming, volume controls, hub settings, MFA authentication.
