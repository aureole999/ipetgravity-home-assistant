# API comparison and implementation evidence

Compared the existing integration with Android APK **宠有引力 1.0.7**, package `com.petgravity.app`, version code 7. APK SHA-256: `bcb1c448991a63aa7e99b1e69f9afa511cdeae6995a8fbdcf455639d3fac09e1`.

The Flutter AOT library uses Dart 3.9.2. Static analysis recovered the API methods, default form encoding, JSON models, and login callbacks. It confirms the same `https://app.ipetgravity.com` API base and custom `token` header used by the previous iOS capture.

## Integrated endpoints

All methods below use POST. Fields are sent as form data unless specified as JSON.

| Path | Request | Integration use | Verification |
|---|---|---|---|
| `/device/getScreen` | Empty form | Discover homes, gateway MAC and fountain ID/MAC | APK + capture + live |
| `/device/water/drinkWaterDataStatistics` | JSON: `screenId`, `startTime`, `endTime`, `type=DAY`, `rfid` | Existing home-level daily drinking sensors | APK + capture + live |
| `/device/water/targetDayDrinkData` | `targetScreenId`, `time` | Existing last-drink sensors | APK + capture + live |
| `/device/water/targetTimeDrinkData` | `targetScreenId`, `startTime`, `endTime`, `type=1` | On-demand daily history action | APK + capture + live |
| `/device/water/todayWaterDeviceData` | `deviceId` | Nine device-specific daily volume/count sensors | APK + live |
| `/device/getDeviceEventList` | `mac`, `time` | Last operation sensors and on-demand event history | APK + live |
| `/pet/getPetTargetInfo` | `screenId` | On-demand pet target action | APK + capture + live empty list |
| `/user/getLoginSmsCode` | `phone` | Send SMS after explicit UI submission | APK + mocked wire/flow tests; no live SMS |
| `/user/loginWithSms` | `phone`, `code` | Obtain `data.token`, then discover devices | APK + mocked wire/flow tests; no live SMS |

Live read-only checks used the integration's actual Python client on 2026-10-28. No device settings were changed. Token values, personal identifiers and raw app code are not included in this repository.

## Login details

- `API.sendSms` posts the phone map to `/user/getLoginSmsCode` using the request wrapper's default `application/x-www-form-urlencoded` encoding.
- `API.loginWithSmsCode` constructs the form with `phone` and `code`. Its callback parses the returned `data` as `UserInfo`; that model contains `userId`, `token`, and profile fields.
- The app's model exposes one normal application token. No access-token/refresh-token pair was found in these login methods. Absence from the examined paths does not establish a guaranteed server-side token lifetime.
- `/user/loginWithToken` is called by **carrier one-click login** (`ali_one_key_login.dart`). Its input is a carrier SDK token. It is not a token-refresh endpoint and is not needed to use an existing app JWT.
- Existing-token login validates through `/device/getScreen`. Decoding the unsigned JWT payload supplies only a stable account identifier, never authentication.

## Device statistics

`todayWaterDeviceData` returns:

| Field | Unit / meaning |
|---|---|
| `drinkVolumeTotal` | Device drinking volume, mL |
| `drinkTimeTotal` | Drinking count |
| `pumpVolumeTotal` | Dispensed volume, mL |
| `pumpPourOutVolumeTotal` | Pour-out volume, mL; vendor field kept distinct from total dispensed volume |
| `pumpTimeTotal` | Dispensing count |
| `replVolumeTotal`, `replTimeTotal` | Refill volume in mL and count |
| `sensVolumeTotal`, `sensTimeTotal` | Sensing dispense volume in mL and count |

The app UI displays the `*TimeTotal` values with `次`; these are not durations. Fields are preserved independently rather than deriving one total from another. The server supplies the day for this endpoint; it accepts no date argument.

Device events contain `eventStr`, `time`, `eventType`, `eventId` and sometimes `result`. Unlike drinking events, these describe device operations, for example a pour-out operation. Text remains in the language supplied by the server.

## Other paths and MQTT

The APK also contains home/pet creation and editing, binding/unbinding, account/profile management, firmware-version checks, feedback and announcement endpoints. These do not provide additional verified fountain telemetry. They are not automatically exposed as control actions.

The app uses `mqtt5_client` and `MqttManager` for live device state and commands. In **0.3.0**, the integration adds that channel, including state parsing, scoped subscription, reconnects and command acknowledgments. Its authentication differs from the HTTP token flow.

## MQTT verification in 0.3.0

The distributed Android client connects using MQTT 5 over TCP port 1883. The integration first authenticates the home through the HTTP token, then subscribes only to these exact device topics (no wildcards):

The examined APK embeds fixed MQTT client credentials. This establishes that app installations use those client defaults; it does not establish the credentials used by gateways or the server's ACL rules. The public integration does not embed those values: users enter MQTT credentials through HA integration options. Read-only testing was limited to the authenticated user's known device topics.

- `v1/{gatewayMac}/D/{deviceMac}` — fountain reports and command replies.
- `v1/{gatewayMac}/G` — gateway replies.
- `v1/gateway/notify/{gatewayMac}` — gateway online notifications.

Requests are published without retain to `v1/{gatewayMac}/S`. Each new request has a unique request ID. Payload MAC addresses are checked again after delivery.

| Command | Meaning | Evidence |
|---|---|---|
| 1 | Gateway child online query | APK + live |
| 2 | Connect/read an already-bound fountain | APK + live; results in fresh 101 and 110 reports |
| 101 | Running state and complete settings report | APK + live |
| 110 | Warning snapshot | APK + live empty all-clear snapshot |
| 102 | One-shot dispensing | APK + mocked command/ack tests only |
| 103 | Update setting sections | APK + mocked command/ack tests only |

Static Dart field-table values resolve setting command `0xf14` to **103**, and dispensing command `0xf0c` to **102**. The app's setting methods preserve section objects such as `autoHeating`, `autoWaterReplenish`, `sensingWater`, `beep`, `childLock`, `exPump`, `remoteDischarge` and `timedWaterDischarge`.

The device used for verification reports firmware code **10015** and `running.weight.current`, while the older APK also supports `running.waterVolume`. The user confirmed the first value of 81 corresponds to the app's 81 mL display. The production integration client subsequently retrieved a fresh 80 mL reading with fresh all-clear warning data. No real settings or dispensing commands were executed.

The app treats a warning value of **-1** as active. The full empty command-110 object observed live means no warnings. This is separate from absence of a warning snapshot, which remains unknown. Water-bowl removal, stale/retained old data and broker disconnects do not become a zero-volume reading.

For command acknowledgments, matching request ID, expected command, device scope, non-retained delivery, freshness and success code 200 are all required. A timeout is an uncertain result and is never retried automatically. After a success acknowledgment, the integration requests the authoritative state again instead of changing the entity optimistically.

The MQTT client provides HA entities only. Alert routing, thresholds used directly on volume, delays, repeat notifications and quiet hours belong to the user's Home Assistant automations. The optional low-water binary entity also provides a configurable hysteresis threshold.
