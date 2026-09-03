"""Integration setup/unload."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.traffical.common.consts import DOMAIN
from custom_components.traffical.models.entity_specs import SCOPE_HUB, get_entity_specs
from custom_components.traffical.sensor import TrafficalSensor
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er

_USER = {
    "sub": "user-sub-1",
    "person": {"memberId": 10, "firstName": "Kid"},
    "customer": {"name": "School", "type": 28},
}


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="user-sub-1",
        data={
            "environment": "Live",
            "api_url": "https://mobile-traffical.mashcal.co.il/",
            "identity_url": "https://identity-traffical.mashcal.co.il/",
            "phone": "0501234567",
            "device_id": "dev-1",
            "app_hash": "",
            "tokens": {
                "access_token": "a",
                "refresh_token": "r",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        },
    )


def _api_patches() -> ExitStack:
    stack = ExitStack()
    stack.enter_context(
        patch(
            "custom_components.traffical.managers.identity_client.IdentityClient.userinfo",
            new_callable=AsyncMock,
            return_value=_USER,
        )
    )
    stack.enter_context(
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.user_roles",
            new_callable=AsyncMock,
            return_value=[],
        )
    )
    stack.enter_context(
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.passenger_policies",
            new_callable=AsyncMock,
            return_value={},
        )
    )
    stack.enter_context(
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.list_rides",
            new_callable=AsyncMock,
            return_value=[],
        )
    )
    stack.enter_context(
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_track",
            new_callable=AsyncMock,
        )
    )
    return stack


@pytest.mark.asyncio
async def test_async_setup_and_unload_entry(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with _api_patches():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.traffical_next_ride") is not None
        assert hass.states.get("sensor.traffical_school_next_ride") is None
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def _legacy_next_ride(hass: HomeAssistant, entry: MockConfigEntry):
    registry = er.async_get(hass)
    return registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "user-sub-1_next_ride",
        suggested_object_id="traffical_school_next_ride",
        config_entry=entry,
    )


@pytest.mark.asyncio
async def test_setup_renames_restored_deleted_entity_id(hass: HomeAssistant) -> None:
    """A unique id restored from deleted_entities keeps the old slug until rename."""
    entry = _entry()
    entry.add_to_hass(hass)
    legacy = _legacy_next_ride(hass, entry)
    assert legacy.entity_id == "sensor.traffical_school_next_ride"
    er.async_get(hass).async_remove(legacy.entity_id)
    with _api_patches():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        assert (
            registry.async_get_entity_id("sensor", DOMAIN, "user-sub-1_next_ride")
            == "sensor.traffical_next_ride"
        )
        assert registry.async_get("sensor.traffical_school_next_ride") is None
        assert hass.states.get("sensor.traffical_next_ride") is not None
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_setup_renames_active_legacy_entity_id(hass: HomeAssistant) -> None:
    """An in-place update still holding the Hebrew slug is renamed on add."""
    entry = _entry()
    entry.add_to_hass(hass)
    legacy = _legacy_next_ride(hass, entry)
    assert legacy.entity_id == "sensor.traffical_school_next_ride"
    with _api_patches():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        assert (
            registry.async_get_entity_id("sensor", DOMAIN, "user-sub-1_next_ride")
            == "sensor.traffical_next_ride"
        )
        assert registry.async_get("sensor.traffical_school_next_ride") is None
        assert hass.states.get("sensor.traffical_next_ride") is not None
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_entity_does_not_shadow_ha_context(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with _api_patches():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        specs = get_entity_specs("sensor", scope=SCOPE_HUB)
        entity = TrafficalSensor(entry.runtime_data, specs[0])
        assert entity._context is None
        ctx = Context()
        entity.async_set_context(ctx)
        assert entity._context is ctx
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
