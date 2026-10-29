"""Load real HA entities, upgrade old entries, and exercise read-only actions."""

import datetime as dt
from copy import deepcopy
from dataclasses import replace

import pytest
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.sensor import recorder as sensor_recorder
from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.ipetgravity.api import (
    PetGravityAuthError,
    PetGravityConnectionError,
)
from custom_components.ipetgravity.diagnostics import async_get_config_entry_diagnostics

from .conftest import TOKEN


async def setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return {
        s.attributes.get("friendly_name"): s for s in hass.states.async_all("sensor")
    }


async def test_upgrade_and_entities(hass, entry, client):
    states = await setup(hass, entry)
    assert entry.data["water_device_id"] == 3
    assert len(states) == 16
    values = [s.state for s in states.values()]
    assert "416" in values and "4" in values and "0" in values
    assert "倾倒出水105ml" in values
    assert entry.runtime_data.coordinator.data.latest_event["intake"] == 10
    client.async_get_device_statistics.assert_awaited_once_with(3)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_volume_sensor_classes_do_not_log_ha_validation_warnings(
    hass, entry, client, caplog
):
    await setup(hass, entry)
    expected = {
        "today_drink_milliliters": "total_increasing",
        "device_drink_volume": "total_increasing",
        "pump_volume": "total_increasing",
        "pump_pour_out_volume": "total_increasing",
        "refill_volume": "total_increasing",
        "sensing_volume": "total_increasing",
    }
    for key, state_class in expected.items():
        entity_id = er.async_get(hass).async_get_entity_id(
            "sensor", "ipetgravity", f"1_aabbccddee01_{key}"
        )
        state = hass.states.get(entity_id)
        assert state.attributes["device_class"] == "volume"
        assert state.attributes["unit_of_measurement"] == "mL"
        assert state.attributes.get("state_class") == state_class
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", "ipetgravity", "1_aabbccddee01_last_drink_milliliters"
    )
    state = hass.states.get(entity_id)
    assert state.attributes.get("device_class") is None
    assert state.attributes["state_class"] == "measurement"
    assert state.attributes["unit_of_measurement"] == "mL"
    assert not any(
        record.name == "homeassistant.components.sensor"
        and "which is impossible considering device class" in record.getMessage()
        for record in caplog.records
    )


async def test_last_drink_reuses_existing_measurement_statistics(hass, entry, client):
    await setup(hass, entry)
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", "ipetgravity", "1_aabbccddee01_last_drink_milliliters"
    )
    state = hass.states.get(entity_id)
    metadata = {
        entity_id: (
            1,
            {
                "mean_type": StatisticMeanType.ARITHMETIC,
                "has_sum": False,
                "name": None,
                "source": "recorder",
                "statistic_id": entity_id,
                "unit_class": "volume",
                "unit_of_measurement": "mL",
            },
        )
    }
    original = deepcopy(metadata)
    issues = []

    def report(issue_type, statistic_id, data):
        issues.append((issue_type, statistic_id))

    # Reproduce the repair raised by 0.4.1/0.4.2 before checking the fix.
    old_attributes = {**state.attributes, "device_class": "volume"}
    old_attributes.pop("state_class")
    old_state = State(entity_id, state.state, old_attributes)
    sensor_recorder._update_issues(report, [old_state], metadata, {})
    assert issues == [("state_class_removed", entity_id)]
    issues.clear()
    sensor_recorder._update_issues(report, [state], metadata, {})
    assert issues == []
    samples = [(float(state.state), state)]
    unit_class, unit, normalized = sensor_recorder._normalize_states(
        hass, metadata, samples, entity_id, None
    )
    assert (unit_class, unit) == ("volume", "mL")
    assert normalized == samples
    assert metadata == original


async def test_v2_id_migration_preserves_entity_identity(hass, entry, client):
    from homeassistant.helpers import entity_registry as er

    from .conftest import SCREEN

    water = replace(SCREEN.water_device, device_id="FountainOpaque03")
    client.async_get_screens.return_value = [
        replace(SCREEN, screen_id="SceneOpaqueId001", water_device=water)
    ]
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "water_device_id": 3}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.unique_id == "42:1" and entry.data["screen_id"] == 1
    assert entry.data["scene_id"] == "SceneOpaqueId001"
    assert entry.data["water_device_id"] == "FountainOpaque03"
    client.async_get_daily_statistics.assert_awaited_once_with(
        "SceneOpaqueId001", entry.runtime_data.coordinator.data.date
    )
    client.async_get_device_statistics.assert_awaited_once_with("FountainOpaque03")
    assert all(
        entity.unique_id.startswith("1_aabbccddee01_")
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    )


async def test_optional_endpoint_failure_preserves_existing_sensors(
    hass, entry, client
):
    client.async_get_device_statistics.side_effect = PetGravityConnectionError()
    states = await setup(hass, entry)
    assert sum(s.state == "unavailable" for s in states.values()) == 9
    assert any(s.state == "14" for s in states.values())
    client.async_get_device_statistics.side_effect = None
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not any(s.state == "unavailable" for s in hass.states.async_all("sensor"))


async def test_midnight_clears_today_events(hass, entry, client):
    await setup(hass, entry)
    client.async_get_daily_events.return_value = {"code": 200, "data": []}
    client.async_get_device_events.return_value = {"code": 200, "data": []}
    await entry.runtime_data.coordinator.async_refresh()
    assert entry.runtime_data.coordinator.data.latest_event is None
    assert entry.runtime_data.coordinator.data.latest_device_event is None


async def test_read_actions(hass, entry, client):
    await setup(hass, entry)
    result = await hass.services.async_call(
        "ipetgravity",
        "get_drinking_history",
        {
            "config_entry_id": entry.entry_id,
            "start_date": "2026-10-22",
            "end_date": "2026-10-28",
        },
        blocking=True,
        return_response=True,
    )
    assert result["data"][0]["intake"] == 14
    client.async_get_drinking_history.assert_awaited_once_with(
        1, dt.date(2026, 10, 22), dt.date(2026, 10, 28)
    )
    result = await hass.services.async_call(
        "ipetgravity",
        "get_pet_targets",
        {"config_entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert result == {"data": []}
    result = await hass.services.async_call(
        "ipetgravity",
        "get_device_events",
        {"config_entry_id": entry.entry_id, "date": "2026-10-28"},
        blocking=True,
        return_response=True,
    )
    assert result["data"][0]["eventStr"] == "倾倒出水105ml"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "ipetgravity",
            "get_drinking_history",
            {
                "config_entry_id": entry.entry_id,
                "start_date": "2026-10-28",
                "end_date": "2026-10-22",
            },
            blocking=True,
            return_response=True,
        )


async def test_diagnostics_redact_credentials(hass, entry, client):
    await setup(hass, entry)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert TOKEN not in str(result)
    assert "AABBCCDDEE01" not in str(result)


async def test_extra_endpoint_auth_failure_starts_reauth(hass, entry, client):
    await setup(hass, entry)
    client.async_get_device_events.side_effect = PetGravityAuthError()
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"].get("source") == "reauth" for flow in flows)


async def test_invalid_and_unloaded_action_entries(hass, entry, client):
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "ipetgravity",
            "get_pet_targets",
            {"config_entry_id": "missing"},
            blocking=True,
            return_response=True,
        )
    await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "ipetgravity",
            "get_pet_targets",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )


async def test_action_auth_error_starts_reauth(hass, entry, client):
    await setup(hass, entry)
    client.async_get_pet_targets.side_effect = PetGravityAuthError()
    with pytest.raises(HomeAssistantError, match="login expired"):
        await hass.services.async_call(
            "ipetgravity",
            "get_pet_targets",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )
    await hass.async_block_till_done()
    assert any(
        flow["context"].get("source") == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )
