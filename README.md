# PetGravity Home Assistant Custom Integration

宠有引力（PetGravity）饮水机的 Home Assistant 自定义集成，可通过 HACS 安装。

支持 **手机号＋短信验证码** 和 **已有 token** 两种登录方式。接口来自 iOS 抓包，并与 Android App 1.0.7 对照验证。

## Features

- UI setup through a Home Assistant config flow.
- Sign in with a mainland China phone number and six-digit SMS code, or paste an existing app token.
- Both methods save the same app token. Phone numbers and SMS codes are not saved in config entries.
- Uses Home Assistant's shared aiohttp client session.
- Uses `ConfigEntry.runtime_data` for runtime client/coordinator state.
- Cloud polling via `DataUpdateCoordinator`.
- Supports reauthentication when PetGravity rejects the token.
- Reauthentication and reconfiguration offer both login methods and preserve the existing home and entity IDs.
- Existing 0.1.x entries discover the device ID automatically after upgrading.

## Entities

- Today drinking volume
- Today drinking count
- Last drinking volume
- Last drinking duration
- Last drinking time
- Device today drinking volume and count
- Today dispensed volume and dispensing count
- Today pour-out volume
- Today refill volume and count
- Today sensing dispense volume and count
- Last device event and event time

There are 16 sensors in total. The original daily drinking totals are home-level statistics; the new device totals refer to the configured fountain. The app displays `*TimeTotal` fields as **counts**, not seconds.

## 登录 / Login

添加集成后，选择以下任一方式：

1. **使用已有 token**：粘贴 App 请求头中的 `token`，验证后选择家庭。
2. **手机号＋短信验证码**：填写中国大陆手机号（可带 `+86`）；提交后发送一条短信。输入六位验证码，集成会取得并保存 token。

验证码重发至少间隔 60 秒；服务器可能施加更长的限制。集成不会自动重发短信。手机号和验证码仅用于当前登录流程，不写入配置条目。手机号登录的实际短信收发尚待用户验证；请求参数已从 APK 确认，HA 流程已通过模拟测试。

The saved token is used for subsequent polling. A new SMS is needed only when signing in again. The observed token remains usable over an extended period; the integration does not invent a short-token refresh cycle. The server may still revoke a token.

## Read-only actions

The following actions return response data and can be used from Home Assistant's action UI or scripts:

| Action | Inputs | Returned data |
|---|---|---|
| `ipetgravity.get_drinking_history` | `config_entry_id`, `start_date`, `end_date` | Daily drinking summaries, up to 31 inclusive days |
| `ipetgravity.get_device_events` | `config_entry_id`, `date` | Device events for a selected day |
| `ipetgravity.get_pet_targets` | `config_entry_id` | Pets and their drinking targets; empty when none are configured |

Example script action (select your PetGravity entry in the UI):

```yaml
action: ipetgravity.get_drinking_history
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  start_date: "2026-10-22"
  end_date: "2026-10-28"
response_variable: drinking_history
```

Each action returns a mapping containing `data`. Historical results are returned on demand; they are not imported into Home Assistant Recorder statistics.

## Install

### HACS custom repository

1. Open HACS.
2. Open the three-dot menu and choose custom repositories.
3. Add this repository URL:

```text
https://github.com/aureole999/ipetgravity-home-assistant
```

4. Choose the `Integration` category.
5. Download PetGravity from HACS.
6. Restart Home Assistant.

### Manual

Copy the `custom_components/ipetgravity` folder into your Home Assistant `config/custom_components/` directory:

```text
config/
  custom_components/
    ipetgravity/
      __init__.py
      manifest.json
      ...
```

Restart Home Assistant, then add the integration from:

```text
Settings -> Devices & services -> Add integration -> PetGravity
```

Choose either SMS login or token login.

## Notes

If PetGravity rejects the saved token, Home Assistant starts reauthentication with both login methods.

Default polling interval is 5 minutes (four read-only requests per update). Failure of an extra device-statistics endpoint only makes its sensors unavailable; original drinking sensors can continue updating.

The current model supports one fountain per PetGravity home. Timestamps returned without an offset are interpreted using Home Assistant's configured timezone; the vendor does not provide a timezone in these responses. The device-totals endpoint always returns the server's current day.

**Protocol boundary:** live water level, water temperature, battery and device controls use the app's separate MQTT channel. They are not exposed by the verified HTTP endpoints and are not implemented in this release. Account deletion, unbinding, firmware flashing and account profile operations are not exposed as HA actions. See [API findings](docs/api.md).

## Validation

Tested with Home Assistant `2026.10.4`. Install development dependencies from `requirements_test.txt`, then run `pytest` and `ruff check .` with Python 3.14. All fixtures use synthetic credentials and identifiers; tests do not contact the vendor or send SMS.

## Version

Current version: `0.2.0`

The bundled icon is sourced from the public web app manifest at `https://www.ipetgravity.com/manifest.json`.
