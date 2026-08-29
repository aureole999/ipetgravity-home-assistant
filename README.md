# PetGravity Home Assistant Custom Integration

This custom integration polls the PetGravity cloud API captured from the iOS app and exposes water fountain sensors in Home Assistant.

## Features

- UI setup through a Home Assistant config flow.
- Token is entered from the UI and stored in the config entry.
- Uses Home Assistant's shared aiohttp client session.
- Uses `ConfigEntry.runtime_data` for runtime client/coordinator state.
- Cloud polling via `DataUpdateCoordinator`.
- Supports reauthentication when PetGravity rejects the token.

## Entities

- Today drinking volume
- Today drinking count
- Last drinking volume
- Last drinking duration
- Last drinking time

## Install

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

Paste the `token` value captured from a PetGravity app request header.

## Notes

The token is a long-lived app login token from the captured API traffic. If PetGravity later rejects it, Home Assistant will start a reauthentication flow and ask for a fresh token.

Default polling interval is 5 minutes.
