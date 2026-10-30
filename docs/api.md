# App 1.2.0 protocol verification

Compared with the user-supplied Android **宠有引力 1.2.0** APK, package `com.petgravity.app`, SHA-256 `6eb6add5a19a34ff2443e566ee028ecac99a857b9cb980e989d59873b9d0a27c`. The Flutter AOT library uses Dart 3.9.2. Version 0.4.0 uses the app's current HTTP endpoints and firmware fields only. There is no legacy endpoint or telemetry-field fallback.

## HTTP endpoints

Base URL: `https://app.ipetgravity.com`. Authenticated requests carry the existing app token in the `token` header. Request formats were recovered from `http/api.dart` and `http/request.dart`.

| Method | Path | Parameters / body | Purpose |
|---|---|---|---|
| GET | `/device/getScreenV2` | None | Homes, gateways and fountains |
| POST | `/device/water/drinkWaterDataStatistics` | JSON: `sceneId`, `startTime`, `endTime`, `type=DAY`, `rfid` | Daily home-level statistics |
| GET | `/device/water/targetDayDrinkDataV2` | Query: `sceneId`, `time` | Individual drinking events for a day |
| GET | `/device/water/todayWaterDeviceDataV2` | Query: `deviceId` | Today's per-device totals |
| POST | `/device/getDeviceEventListV2` | JSON: `mac`, `time` | Device operation history |
| POST | `/pet/getPetTargetInfo` | Form: `sceneId` | Pets and drinking targets |
| POST | `/user/getLoginSmsCode` | Form: `phone` | Send one login SMS after UI submission |
| POST | `/user/loginWithSms` | Form: `phone`, `code` | Return `data.token` |

The authenticated read endpoints were tested with the user's own account on 2026-10-28. SMS request and response formats were checked statically and with mock tests; no SMS was sent. The same long-lived app token works with the V2 requests. No access/refresh token pair was found in the examined login methods; server-side token lifetime is not guaranteed.

Discovery returns `data.screens`, with `sceneId`, `sceneName`, and `devices`. Device type **0** is a gateway; its type **1** children are Bluetooth fountains. Scene and device IDs are opaque strings, including letters, and differ from earlier server IDs for the same MAC. They are preserved exactly as strings in configuration and cloud requests, with no numeric conversion.

On upgrade, the integration matches the configured fountain MAC against the current device list and saves the V2 scene/device IDs. The existing Home Assistant `screen_id` and entity unique IDs remain stable. Token replacement also matches by MAC and verifies the account ID. New discovery cannot create a duplicate of an existing fountain after the ID change.

The history action uses the DAY statistics endpoint once per selected day and returns `{time, intake, bout}` daily summaries. Live comparison confirmed that DAY mode ignores a supplied multi-day end date, so a single DAY call cannot represent an arbitrary date range. The action is bounded to 31 days; periodic polling remains four reads every five minutes.

## Statistics and events

Per-device totals preserve these independent fields:

- `drinkVolumeTotal` / `drinkTimeTotal`: drinking mL / count.
- `pumpVolumeTotal` / `pumpTimeTotal`: dispensing mL / count.
- `pumpPourOutVolumeTotal`: pour-out mL.
- `replVolumeTotal` / `replTimeTotal`: refill mL / count.
- `sensVolumeTotal` / `sensTimeTotal`: sensing dispense mL / count.

The app displays `*TimeTotal` as counts, not durations. Device events contain `eventStr`, `time`, `eventType`, `eventId`, and sometimes `result`. They are separate from individual drinking events.

## MQTT and current firmware fields

The gateway-connected Bluetooth fountain continues to use MQTT 5 on TCP port 1883. MQTT credentials are entered in HA options; the public repository contains no vendor credential values. The HTTP token is not sent to MQTT. Subscriptions are limited to the authenticated user's exact gateway/fountain topics:

- `v1/{gatewayMac}/D/{deviceMac}` — fountain reports and command replies.
- `v1/{gatewayMac}/G` — gateway replies.
- `v1/gateway/notify/{gatewayMac}` — gateway online notifications.

Requests publish without retain to `v1/{gatewayMac}/S`, using unique request IDs. Payload MACs are checked. The app's separate standalone dual-band Wi-Fi protocol is outside this integration's supported hardware.

| Command | Meaning | Verification |
|---|---|---|
| 1 | Query gateway child online state | Static + live |
| 2 | Connect/read an already-bound fountain | Static + live; produces 101/110 reports |
| 3 | Read gateway information, omitting `data`; retain only firmware code/time | Static + live; same app method can edit settings only when `data` is supplied |
| 101 | Running state and settings snapshot | Static + live |
| 110 | Warning snapshot | Static + live empty all-clear snapshot |
| 102 | One-shot dispensing; `data.type=5` means pour-only | Static + mocked command/ack tests |
| 103 | Update setting sections | Static + mocked command/ack tests |

Current field definitions follow these recovered App 1.2.0 functions:

| HA value | Current field / rule | App evidence |
|---|---|---|
| Bowl water volume, mL | `running.weight.current` | `getWaterVolumeStr` at `0x9303e8` reads `Running.weight.current`; shared by the Bluetooth fountain page |
| Water temperature, °C | `running.heating.ntcTemperature` | `getTempStr` at `0x930124` reads `Running.heating.ntcTemperature` |
| Warning active | Numeric `-1` or `1` | `WaterDeviceWarningInfo.isActive` at `0x937d04` |
| Self-cleaning | `running.selfClean.status == 1` | `SelfClean.isOn` at `0x9300a8` |
| Self-clean raw status / times | `running.selfClean.status`, `.times` | `SelfClean` JSON model; times is not interpreted as a lifetime total |
| Drinking activity | Boolean `running.inDrinkingWater` | `Running.fromJson` accepts a bool, otherwise null |

Missing or invalid current fields stay unknown. Removed bowls, expired reports and offline devices do not produce a zero-volume reading. A complete empty 110 object is confirmed all-clear; no warning snapshot is unknown. The optional low-water binary sensor has a configurable threshold and recovery margin. Notifications remain the user's HA automations.

`WaterDeviceState2._shouldBlockForSelfClean` blocks interactions while self-cleaning. The integration applies this check before sending 102/103, including after acquiring its command lock. State reads remain allowed. The app's standard one-shot command uses the default type 0 and omits `data`, which is unchanged in HA.

Version 0.4.2 adds an independent pour-only button. The `waterDeviceWashBowlDesc` localization is “只倾倒不出水” / “Tip only”; its Bluetooth-page callback invokes `_sendWaterOutByType`, which supplies type **5** to `waterOutCommand`. The UI requires gateway `deviceInfo.firmwareVersionCode > 10004` and fountain `softVersionCode > 10014`. HA checks those exact boundaries, fresh reports from both devices, and self-clean state. The capability check runs again inside the command lock before sending. Unknown firmware leaves the button unavailable. A new read-only command 3 fetches gateway firmware with the regular refresh; it never includes a settings body. Guided self-clean start remains in the app.

Read-only production-client verification on 2026-10-29 received command-3 firmware code **10005** and command-101 fountain code **10015**, enabling pour-only support. Only the code and report timestamp are retained from the gateway response; network settings are not stored. The new physical action was verified with mocked wire payloads and acknowledgments, including no automatic retry after timeout; it was not performed on the user's real fountain during development.

Settings retain the reported fields of their section, including `autoHeating`, `autoWaterReplenish`, `sensingWater`, `beep`, `childLock`, `exPump`, `remoteDischarge`, and `timedWaterDischarge`. Commands require fresh state and matching, non-retained, successful acknowledgments. A timed-out physical action is never retried automatically. No live dispensing, heating, self-clean start or setting changes were performed to validate this release.

## MQTT control success codes (0.4.4)

App 1.2.0 `MqttCommand.isRespSuccess` at `0x926b18` explicitly accepts a numeric response code of **200 or 0**. The previous integration accepted only 200 and ignored 0, so a valid zero-code acknowledgment could leave a completed physical action waiting until the 20-second timeout. Version 0.4.4 accepts both success codes for a matched active control request. Booleans and numeric-looking strings are not accepted as success codes. Request ID, expected command, gateway/device scope, timestamp freshness and non-retained delivery remain required. HTTP responses and unsolicited MQTT telemetry retain their existing 200-only validation.

HA logs on 2026-10-30 showed a normal dispensing button press at 14:00:26 followed by an acknowledgment timeout at 14:00:46 (Asia/Tokyo). These logs do not contain the original MQTT reply, so its actual code cannot be confirmed retrospectively. The zero-code incompatibility was independently reproduced in regression tests and checked against the APK. Both HA button service paths and settings commands are covered; no additional physical operation was performed while diagnosing this report.

Other App 1.2.0 endpoints handle standalone hardware, pet/account edits, binding, firmware updates, feedback, and analysis. They are not required for these entities and are not exposed as unverified control actions.
