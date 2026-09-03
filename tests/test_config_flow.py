"""Config flow and reauth tests for Traffical."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.traffical.common.consts import (
    API_URL,
    DOMAIN,
    IDENTITY_URL,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

_USER = {
    "sub": "user-sub-1",
    "person": {"memberId": 10, "firstName": "A", "lastName": "B"},
    "customer": {"name": "School", "type": 28},
}


@pytest.mark.asyncio
async def test_config_flow_user_success(hass: HomeAssistant) -> None:
    with (
        patch(
            "custom_components.traffical.config_flow.IdentityClient.request_otp",
            new_callable=AsyncMock,
            return_value=("ticket", 60),
        ),
        patch(
            "custom_components.traffical.config_flow.IdentityClient.authorize",
            new_callable=AsyncMock,
            return_value="code-1",
        ),
        patch(
            "custom_components.traffical.config_flow.IdentityClient.exchange_code",
            new_callable=AsyncMock,
            return_value={"access_token": "a", "refresh_token": "r"},
        ),
        patch(
            "custom_components.traffical.config_flow.IdentityClient.userinfo",
            new_callable=AsyncMock,
            return_value=_USER,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"phone": "0501234567"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "otp"
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"], {"otp": "123456"}
        )
        await hass.async_block_till_done()

    assert result3["type"] == FlowResultType.CREATE_ENTRY
    assert result3["result"].unique_id == "user-sub-1"
    assert result3["data"]["phone"] == "0501234567"
    assert result3["data"]["environment"] == "Live"
    assert result3["data"]["api_url"] == API_URL
    assert result3["data"]["identity_url"] == IDENTITY_URL


@pytest.mark.asyncio
async def test_config_flow_reauth(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user-sub-1",
        data={
            "environment": "Live",
            "phone": "0501234567",
            "api_url": "https://mobile-traffical.mashcal.co.il/",
            "identity_url": "https://identity-traffical.mashcal.co.il/",
            "device_id": "dev-1",
            "app_hash": "",
            "tokens": {"refresh_token": "old"},
        },
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.traffical.config_flow.IdentityClient.request_otp",
            new_callable=AsyncMock,
            return_value=("ticket", 60),
        ),
        patch(
            "custom_components.traffical.config_flow.IdentityClient.authorize",
            new_callable=AsyncMock,
            return_value="code-1",
        ),
        patch(
            "custom_components.traffical.config_flow.IdentityClient.exchange_code",
            new_callable=AsyncMock,
            return_value={"access_token": "a2", "refresh_token": "r2"},
        ),
        patch(
            "custom_components.traffical.config_flow.IdentityClient.userinfo",
            new_callable=AsyncMock,
            return_value=_USER,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
                "unique_id": entry.unique_id,
            },
            data=dict(entry.data),
        )
        assert result["type"] == FlowResultType.FORM
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp": "999111"}
        )
        await hass.async_block_till_done()
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
