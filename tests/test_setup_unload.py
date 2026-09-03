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
