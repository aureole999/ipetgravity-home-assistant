# PetGravity Home Assistant Custom Integration

宠有引力（PetGravity）饮水机的 Home Assistant 自定义集成，可通过 HACS 安装。

支持 **手机号＋短信验证码** 和 **已有 token** 两种登录方式。HTTP 接口与实时字段已按 Android App **1.2.0** 核对，使用新版 V2 设备列表与统计接口。

## Features

- UI setup through a Home Assistant config flow.
- Sign in with a mainland China phone number and six-digit SMS code, or paste an existing app token.
- Both methods save the same app token. Phone numbers and SMS codes are not saved in config entries.
- Uses Home Assistant's shared aiohttp client session.
- Uses `ConfigEntry.runtime_data` for runtime client/coordinator state.
- Cloud polling via `DataUpdateCoordinator`.
- Supports reauthentication when PetGravity rejects the token.
- Reauthentication and reconfiguration offer both login methods and preserve the existing home and entity IDs.
- Existing entries discover the new scene/device IDs by fountain MAC after upgrading; Home Assistant entity IDs and their history are preserved.

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

These 16 HTTP sensors remain available. The original daily drinking totals are home-level statistics; the device totals refer to the configured fountain. The app displays `*TimeTotal` fields as **counts**, not seconds.

Daily volume totals use HA's `total_increasing` state class to support daily resets. Last-drink volume is the latest individual reading: it uses `measurement` with mL and no cumulative `volume` device class. This preserves its existing mean/min/max statistics; those statistics describe the retained latest readings over time, not a sum of drinking sessions. Live bowl volume uses `volume_storage` with `measurement`, as it measures the water currently held in the bowl. Entity IDs, values and mL units stay the same.

If 0.4.1 or 0.4.2 raised “state class removed” for last-drink volume, **do not delete its long-term statistics**. Update to 0.4.3 and restart HA. The restored state class matches the existing measurement statistics; HA can clear the repair on its next statistics validation. Data already deleted cannot be recovered by this update, and the update does not backfill the recording gap.

## MQTT 实时状态与控制

不需要安装本地 MQTT broker，也不需要修改 HA 中已有的 MQTT 集成。PetGravity 直接连接厂商 MQTT 服务，只订阅通过账号发现的网关和饮水机。

首次启用：更新后打开“设置 → 设备与服务 → PetGravity → 配置”，填写从 App 获取的 MQTT 用户名和密码，再启用 MQTT。连接凭据保存在你的 HA 配置中，公开仓库不包含这些值。尚未填写时，原有 HTTP 饮水统计继续工作。

| 类型 | 新增功能 |
|---|---|
| 水量 | 水碗水量（mL）、水碗水量不足、水碗是否安装 |
| 水箱与故障 | 净水箱缺水、污水箱满、两个水箱未安装、水碗未安装、加热故障、称重故障、倾倒故障、低电量告警 |
| 其它状态 | MQTT 连接、设备在线、最近上报时间、电量、充电状态、温度、加热功率、出水及外接水泵状态、自清洁状态/次数、正在饮水 |
| 开关 | 自动加热、自动补水、感应出水、提示音、童锁 |
| 参数 | 目标温度、补水阈值/水量/间隔、感应阈值/水量/间隔、手动出水量、定时与节水模式参数、外接水泵补水/排水时长 |
| 模式与操作 | 定时模式、外接水泵模式、自定义出水计划、倾倒出水一次、只倾倒不加水、刷新设备状态 |

没有上报的项目显示未知。原始状态代码不解释为未经确认的设备状态；自清洁次数直接显示 `selfClean.times`，不假定它是累计清洁总次数。

与新版 App 一致，水碗水量只读取 `running.weight.current`，水温只读取 `running.heating.ntcTemperature`；不再回退到旧字段。原有“加热传感器温度”实体仍保留，与水温使用同一传感器读数。告警值 `-1` 或 `1` 都表示有效告警。新字段缺失时显示未知，不以旧字段或零补齐。

`selfClean.status == 1` 表示正在自清洁。期间出水与修改设置操作会被拒绝，刷新和状态读取继续工作。自清洁启动需要 App 的水箱准备引导，本集成只提供状态读取。

“只倾倒，不加水”是独立按钮，对应 App 的“只倾倒不出水”，发送 `102` + `data: {"type": 5}`。它只发送一次倾倒动作，不修改自动补水开关或水量设置。原有“倾倒出水一次”按钮保持普通出水行为。

与 App 一样，该按钮要求网关固件 **高于 v1.0.4**、饮水机固件 **高于 v1.0.14**。集成通过只读网关信息查询取得版本；版本信息尚未取得、已过期、固件不支持、设备离线或正在自清洁时，按钮不可用。可以先点击“刷新设备状态”。按钮等到匹配的设备回执后才返回成功，超时不自动重试。

超过 15 分钟的保留消息不会被当成当前状态。15 分钟内没有有效新上报、MQTT 断开或设备明确离线时，实时实体会变为不可用。设备主动上报会立即更新；集成也每 5 分钟使用 App 的查询/已绑定设备连接请求读取状态。移除水碗时水量不会当作 0 mL。

控制命令需要新鲜状态和匹配的设备回执，保留同一设置中其它参数。超时后不会自动重发出水或设置命令。**实时读取已实测；设置和出水操作已核对 APK 并通过模拟测试，未对真实设备执行出水、加热或改设置来测试。**

### 在 HA 中设置水位通知

通知由你自己的 HA 自动化负责，集成不会创建自动化或发送通知：

- 水碗提醒：使用“水碗水量”设置自己希望的数值阈值和持续时间；也可以使用“水碗水量不足”状态。这个状态默认低于 50 mL 开启，加水到 70 mL 恢复，可在集成选项中修改。
- 净水箱提醒：使用“净水箱缺水”状态从关闭变为开启。
- 污水箱提醒：使用“污水箱已满”状态从关闭变为开启。

在“设置 → 设备与服务 → PetGravity → 配置”中，可以启用/关闭 MQTT、调整低水量状态阈值及恢复余量。通知对象、是否重复提醒、静默时段等放在 HA 自动化中设置。

### 自定义出水计划

`ipetgravity.set_dispensing_schedule` 保存并启用 1 至 12 个每天的出水时间点。每个时间点包含 `time`（`HH:MM`）及 `volume`（1 至 200 mL）；时间使用设备/App 的本地时间。该操作保留其它模式的参数，并切换至自定义计划模式。

```yaml
action: ipetgravity.set_dispensing_schedule
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  schedule:
    - time: "08:00"
      volume: 80
    - time: "20:00"
      volume: 80
```

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

Each action returns a mapping containing `data`. Historical results are returned on demand; they are not imported into Home Assistant Recorder statistics. A history query makes one request per selected day to the current app's DAY statistics API, up to 31 requests; it does not affect periodic polling.

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

HTTP polling interval is 5 minutes (four read-only requests per update). Failure of MQTT or an extra device-statistics endpoint does not stop the original HTTP drinking sensors.

The current model supports one gateway-connected Bluetooth fountain per PetGravity home. The standalone dual-band Wi-Fi fountain introduced in App 1.2.0 uses another MQTT protocol and is not supported. Timestamps returned without an offset are interpreted using Home Assistant's configured timezone; the vendor does not provide a timezone in these responses. The device-totals endpoint always returns the server's current day.

Version 0.4.0 uses the current app interfaces only, with no legacy endpoint fallback. When upgrading, keep the existing integration entry: its internal `screen_id` remains the Home Assistant identity, while the new `scene_id` and device ID are used for cloud requests. Reauthentication preserves this separation too.

The cloud MQTT connection follows the app's TCP protocol. Its username and password are supplied through integration options, separate from the user's HTTP token; no MQTT credentials are bundled in the public repository, and the HTTP token is never sent to the MQTT broker. Access requires an outbound connection to the vendor on port 1883. Account deletion, unbinding, firmware flashing, weighing calibration and gateway network changes are not exposed as HA actions. See [API findings](docs/api.md).

## Validation

Tested with Home Assistant `2026.10.4`. Install development dependencies from `requirements_test.txt`, then run `pytest` and `ruff check .` with Python 3.14. All fixtures use synthetic credentials and identifiers; tests do not contact the vendor or send SMS.

## Version

Current version: `0.4.3`

The bundled icon is sourced from the public web app manifest at `https://www.ipetgravity.com/manifest.json`.
