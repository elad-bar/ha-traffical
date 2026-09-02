"""Coordinator poll and ride-device identity."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.traffical.common.consts import DOMAIN
from custom_components.traffical.managers.coordinator import async_create_coordinator
from custom_components.traffical.models.rides import ride_device_key
from homeassistant.core import HomeAssistant

_USER = {
    "sub": "user-sub-1",
    "person": {"memberId": 10, "firstName": "Kid"},
    "customer": {"name": "School", "type": 28},
}

_RIDE = {
    "status": "New",
    "name": "Morning",
    "routeId": 392681,
    "direction": 120,
    "rideInfo": {
        "rideId": 39306112,
        "rideTicket": "t1",
        "routeId": 392681,
        "direction": 120,
        "passengerStationName": "Home",
    },
}

_DETAILS = {
    "rideId": 39306112,
    "routeId": 392681,
    "direction": 120,
    "status": "New",
    "name": "Morning",
    "stations": [
        {
            "stationId": 1,
            "name": "Home",
            "address": "1 Main",
            "lat": 32.0,
            "lng": 34.8,
            "passengers": [{"id": 10}],
        },
        {
            "stationId": 2,
            "name": "School",
            "address": "2 School",
            "lat": 32.1,
            "lng": 34.9,
            "isTarget": True,
        },
    ],
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


@pytest.mark.asyncio
async def test_coordinator_ride_key_not_daily_id(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.traffical.managers.identity_client.IdentityClient.userinfo",
            new_callable=AsyncMock,
            return_value=_USER,
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.user_roles",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.passenger_policies",
            new_callable=AsyncMock,
            return_value={"gotOnRideReport": {"isActive": True}},
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.list_rides",
            new_callable=AsyncMock,
            return_value=[_RIDE],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.checkin_statuses",
            new_callable=AsyncMock,
            return_value=[{"rideId": 39306112, "checkIn": False}],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.ride_details",
            new_callable=AsyncMock,
            return_value=_DETAILS,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_track",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_track",
            new_callable=AsyncMock,
        ),
    ):
        coordinator = await async_create_coordinator(hass, entry)
        await coordinator.async_start()
        try:
            key = ride_device_key(392681, 120)
            assert key in coordinator.ride_keys
            ride = coordinator.ride(key)
            assert ride["ride_id"] == 39306112
            assert ride["assigned_today"] is True
            assert coordinator.policy_active("gotOnRideReport")
            assert coordinator.data["focus_ride_key"] == key
        finally:
            await coordinator.async_stop()
