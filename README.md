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

Paste the `token` value captured from a PetGravity app request header.

## Notes

The token is a long-lived app login token from the captured API traffic. If PetGravity later rejects it, Home Assistant will start a reauthentication flow and ask for a fresh token.

Default polling interval is 5 minutes.
