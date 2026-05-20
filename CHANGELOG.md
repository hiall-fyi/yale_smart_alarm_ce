# Changelog

All notable changes to Yale Smart Alarm CE are documented here.

---

## 1.0.0 — First Stable Release (2026-05-20)

End of beta. Big thanks to the testers whose bug reports and
diagnostics directly drove fixes in this release —
[@PV-44](https://github.com/PV-44),
[@lleraman](https://github.com/lleraman),
[@tombaptist](https://github.com/tombaptist),
[@simonrb2000](https://github.com/simonrb2000),
[@GTunney](https://github.com/GTunney), and
[@AlexBrown92](https://github.com/AlexBrown92).
Specific contributions are credited inline below.

### Final fixes since the last beta (0.1.2)

- **Force arm service now actually works** ([#2](https://github.com/hiall-fyi/yale_smart_alarm_ce/issues/2)) — The `yale_smart_alarm_ce.force_arm` service shipped in 0.1.2 sent the alarm hub ID where Yale expected an area ID, so every call was rejected. The service now reads the same area IDs the regular Arm Home / Arm Away buttons use, so bypassing open sensors works as advertised.
- **Rate-limit warnings no longer drown out the real signal** — When Yale temporarily throttles the integration (HTTP 429), the integration now pauses polling for the duration the server asks for, and Home Assistant surfaces a clear repair issue instead of repeating "failed to fetch devices" warnings every 30 seconds. Previously these throttle responses were silently swallowed for sensor / lock / device / doorbell fetches, so a throttled account kept hammering the API and made its own rate-limit worse.
- **Network blips alongside CDN issues no longer give up early on retries** — If the integration hit a mix of transient errors during a single request (for example a CDN-level block followed by a connection reset), the retry budget could exhaust before either error class had its chance. Each error class now gets its own independent retry counter, so the integration sees the request through more of these mixed transient failures.

### What the beta delivered (0.1.0 → 0.1.2)

#### Alarm control

- **Arm Home, Arm Away, Disarm** with multi-area support — each area shows up as its own panel with its own zone name (the multi-zone fix landed in 0.1.1 after @lleraman, @tombaptist, @simonrb2000 reported every area showing up as just "Alarm").
- **Arming transitional state** — the dashboard now shows "Arming" during the exit-delay countdown instead of staying on "Disarmed" until the next poll (added in 0.1.1 after @AlexBrown92, @tombaptist asked for it). The `exit_delay_end` attribute exposes the absolute end timestamp for automations.
- **Force arm with open sensors** — `yale_smart_alarm_ce.force_arm` service lets you arm while bypassing specific open sensors. When arming is blocked, you get a clear "Cannot arm — Front Door (open)" message listing exactly which sensors are blocking. A `yale_smart_alarm_ce_arm_blocked` event also fires so automations can notify you or close the door before retrying. (Added in 0.1.2 after @PV-44 hit the cryptic HTTP 409 from Yale; the underlying area-ID dispatch bug was finally fixed in 1.0.0.)
- **Multi-zone independent control** — separate panels per zone, each one tracks its own exit-delay countdown so arming one zone doesn't flash "Arming" on every other zone.

#### Sensors and devices

- **Contact sensors** — door / window open / close, indoor + outdoor + shock variants.
- **Smoke sensors** — smoke detection and fault state.
- **PIR motion sensors** — battery, connectivity, and tamper at the device level. Note: the per-sensor "motion detected" entity was removed in 0.1.2 because Yale only delivers motion through a real-time push channel that this integration doesn't speak yet — the sensor was permanently stuck on "Clear". Alarm triggering still works correctly; you just don't see per-sensor motion.
- **Smart locks** — lock / unlock with door state, battery percentage, jammed detection, and transitional states (locking, unlocking). Tested across Yale Linus L2, Conexis L1/L2, Keyless Connected, and the Yale Smart Safe. Lock state is preserved during transient API errors so you don't see false "unlocked" readings.
- **Battery monitoring** — low-battery binary sensor for every sub-device, percentage sensor for the hub and locks.
- **Connectivity, tamper, RF jamming** — diagnostic sensors covering the hub and every connected device.
- **Panic buttons** — RF panic button activation state.
- **Doorbells** — doorbell press detection.

#### Hub controls and settings

- **Volume controls** — siren, chime, and trouble volume (OFF / LOW / MID / HIGH) at the hub and on individual sirens.
- **Outdoor siren controls** — Comfort LED and Strobe switches for outdoor models, surfaced separately from indoor sirens (added in 0.1.1 after @lleraman, @tombaptist confirmed the hardware capability).
- **Hub setting switches** — White LED, tamper detection, RF jam detection, force arm, cellular backup, WiFi, daylight savings, RF supervisory, keypad quickset.
- **Device setting switches** — Entry / exit tones (sirens), proximity wakeup (keypads).

#### Setup and operation

- **MFA-aware setup flow** — email verification code support during setup; install ID is preserved across re-authentication so Yale doesn't email a new code every time the session refreshes.
- **Reconfigure without removing** — change your password or region from the integration card. Settings prompts now make it clear ("The alarm must be disarmed before changing settings") instead of surfacing the raw HTTP 412 from Yale.
- **Multi-region support** — Global (EU, UK, US), China, Gateman (Korea), Lockwood (Australia / NZ).
- **Diagnostics** — download a redacted diagnostics report from the integration card. Lock PII and credentials (PIN codes, user names, encryption keys, serial numbers, bridge identifiers) are stripped automatically (hardening in 0.1.1 + 0.1.2 after @lleraman, @PV-44 spotted leaks).
- **Repair issues** — auth expiry and rate limiting show up in Settings → Repairs.
- **HACS support** — install and update through HACS as a custom repository.

#### Reliability

- Automatic retry for transient API errors and network issues, with randomised backoff so multiple HA instances recovering from an outage don't all hammer Yale at once.
- Yale's CDN occasionally serves transient HTTP 403 — the integration retries before surfacing it as an auth error.
- Stale-device cleanup is skipped when the API returns an empty device list, so devices don't disappear from HA on a single failed poll (fix in 0.1.2 after reports from @GTunney, @tombaptist).
- The lock-status repoll-on-unknown timer is cancelled cleanly during integration unload, so reload no longer leaves a stray timer firing into a disposed coordinator.

### Known limitations

- **Cloud-only** — all control goes through Yale's cloud servers.
- **Polling only** — no real-time push notifications; the integration polls at your configured interval (default 30 seconds, range 10–300 seconds).
- **No PIR motion state entity** — see the Sensors note above. PIR alarms still trigger correctly; you just don't see per-sensor motion events between polls.
- **No temperature sensors** — Yale returns readings that can be months old with no staleness indicator, so they've been removed entirely.
- **Settings require disarm** — Yale requires the alarm disarmed before configuration changes. Use force_arm for the arm-with-open-sensor case.
- **No schedule management** — use the Yale Home app for schedule changes.

### Region testing status

Global (EU / UK / US) is verified. China, Gateman (Korea), and Lockwood (Australia / NZ) are supported in code but haven't been confirmed with real hardware — feedback welcome.
