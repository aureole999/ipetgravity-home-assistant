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

The app uses `mqtt5_client` and `MqttManager` for live device state and commands. Water level, temperature, battery, heating, dispensing, child lock, timers and external-pump control need that protocol, including message parsing and acknowledgments. Its authentication differs from the HTTP token flow. Static identification alone is insufficient to claim these controls work; no MQTT commands were sent or added in 0.2.0.
