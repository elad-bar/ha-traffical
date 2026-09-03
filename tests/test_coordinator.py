"""Coordinator poll and ride-device identity."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.traffical.common.consts import DOMAIN
from custom_components.traffical.managers.coordinator import async_create_coordinator
from custom_components.traffical.models.rides import ride_device_key
from homeassistant.config_entries import ConfigEntryState
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


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    """Register an entry mid-setup, as HA does before starting a coordinator."""
    entry = MockConfigEntry(
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
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    return entry


@pytest.mark.asyncio
async def test_coordinator_ride_key_not_daily_id(hass: HomeAssistant) -> None:
    entry = _entry(hass)
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
        ) as list_rides,
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
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_mobile",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_track",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_mobile",
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
            assert coordinator.data["focus"]["ride_id"] == 39306112
            assert list_rides.await_count == 1
            await coordinator.async_request_refresh()
            assert list_rides.await_count == 2
        finally:
            await coordinator.async_stop()


@pytest.mark.asyncio
async def test_mobile_hub_status_starts_live_tracking(hass: HomeAssistant) -> None:
    entry = _entry(hass)
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
            return_value={},
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.list_rides",
            new_callable=AsyncMock,
            return_value=[_RIDE],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.checkin_statuses",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.ride_details",
            new_callable=AsyncMock,
            return_value=_DETAILS,
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.monitoring_path",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_mobile",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_mobile",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_track",
            new_callable=AsyncMock,
        ) as start_track,
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_track",
            new_callable=AsyncMock,
        ),
    ):
        coordinator = await async_create_coordinator(hass, entry)
        await coordinator.async_start()
        try:
            await coordinator._on_mobile_hub_event(
                "UpdateRideStatus",
                {"Id": 39306112, "Status": "OngoingMonitored"},
            )
            key = ride_device_key(392681, 120)
            assert coordinator.ride(key)["status"] == "OngoingMonitored"
            assert coordinator.data["live_key"] == key
            start_track.assert_awaited_once()
        finally:
            await coordinator.async_stop()


_FINISHED_TODAY = {
    "status": "Finished",
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

_TOMORROW_RIDE = {
    "status": "New",
    "name": "Morning",
    "routeId": 392681,
    "direction": 120,
    "rideInfo": {
        "rideId": 40000001,
        "rideTicket": "t2",
        "routeId": 392681,
        "direction": 120,
        "passengerStationName": "Home",
    },
}

_TOMORROW_DETAILS = {
    "rideId": 40000001,
    "routeId": 392681,
    "direction": 120,
    "status": "New",
    "name": "Morning",
    "startTime": "2026-09-03T05:00:00Z",
}


def _finished_details() -> dict:
    body = dict(_DETAILS)
    body["status"] = "Finished"
    body["startTime"] = "2026-09-02T05:00:00Z"
    return body


async def _list_finished_and_tomorrow(_customer_type: str, date_str: str):
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    if date_str == today:
        return [_FINISHED_TODAY]
    if date_str == tomorrow:
        return [_TOMORROW_RIDE]
    return []


async def _details_by_ticket(ticket: str):
    if ticket == "t2":
        return _TOMORROW_DETAILS
    return _finished_details()


@pytest.mark.asyncio
async def test_coordinator_keeps_finished_today_focus_tomorrow(
    hass: HomeAssistant,
) -> None:
    entry = _entry(hass)
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
            return_value={},
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.list_rides",
            new_callable=AsyncMock,
            side_effect=_list_finished_and_tomorrow,
        ) as list_rides,
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.checkin_statuses",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.ride_details",
            new_callable=AsyncMock,
            side_effect=_details_by_ticket,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_track",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_mobile",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_track",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_mobile",
            new_callable=AsyncMock,
        ),
    ):
        coordinator = await async_create_coordinator(hass, entry)
        await coordinator.async_start()
        try:
            key = ride_device_key(392681, 120)
            ride = coordinator.ride(key)
            assert ride["ride_id"] == 39306112
            assert ride["status"] == "Finished"
            assert ride["assigned_today"] is True
            focus = coordinator.data["focus"]
            assert focus["ride_id"] == 40000001
            assert coordinator.data["focus_ride_key"] is None
            await coordinator._on_mobile_hub_event(
                "UpdateRideStatus",
                {"Id": 39306112, "Status": "FinishedMonitored"},
            )
            assert coordinator.ride(key)["status"] == "FinishedMonitored"
            assert coordinator.data["focus"]["ride_id"] == 40000001
            assert list_rides.await_count == 2
            await coordinator.async_request_refresh()
            assert list_rides.await_count == 2
        finally:
            await coordinator.async_stop()


@pytest.mark.asyncio
async def test_stop_does_not_rearm_signalr(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with (
        patch(
            "custom_components.traffical.managers.identity_client.IdentityClient.userinfo",
            new_callable=AsyncMock,
            return_value=_USER,
        ),
        patch(
            "custom_components.traffical.managers.identity_client.IdentityClient.refresh",
            new_callable=AsyncMock,
            return_value={
                "access_token": "a2",
                "refresh_token": "r2",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.user_roles",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.passenger_policies",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.list_rides",
            new_callable=AsyncMock,
            return_value=[_RIDE],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.checkin_statuses",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.ride_details",
            new_callable=AsyncMock,
            return_value=_DETAILS,
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.monitoring_path",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_track",
            new_callable=AsyncMock,
        ) as start_track,
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_mobile",
            new_callable=AsyncMock,
        ) as start_mobile,
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_track",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_mobile",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.restart",
            new_callable=AsyncMock,
        ) as restart,
    ):
        coordinator = await async_create_coordinator(hass, entry)
        await coordinator.async_start()
        mobile_calls = start_mobile.await_count
        track_calls = start_track.await_count
        restart_calls = restart.await_count
        await coordinator.async_stop()
        await coordinator._sync_signalr(
            "392681:120", {"392681:120": {"ride_id": 39306112}}
        )
        assert await coordinator._refresh_tokens() is True
        assert start_mobile.await_count == mobile_calls
        assert start_track.await_count == track_calls
        assert restart.await_count == restart_calls


@pytest.mark.asyncio
async def test_entity_listeners_fire_when_focus_key_changes_not_on_gps(
    hass: HomeAssistant,
) -> None:
    entry = _entry(hass)
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
            return_value={},
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.list_rides",
            new_callable=AsyncMock,
            return_value=[_RIDE],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.checkin_statuses",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.ride_details",
            new_callable=AsyncMock,
            return_value=_DETAILS,
        ),
        patch(
            "custom_components.traffical.managers.mobile_client.MobileClient.monitoring_path",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.start_mobile",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.traffical.managers.signalr_client.SignalRHubs.stop_mobile",
            new_callable=AsyncMock,
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
            hits: list[int] = []
            coordinator.register_entity_listener(lambda: hits.append(1))
            await coordinator._on_mobile_hub_event(
                "UpdateRideStatus",
                {"Id": 39306112, "Status": "OngoingMonitored"},
            )
            assert hits == []
            await coordinator._on_hub_event(
                "ReceiveCoordinates",
                {"Latitude": 32.12, "Longitude": 34.8, "SourceType": 2},
            )
            assert hits == []
            await coordinator._on_mobile_hub_event(
                "UpdateRideStatus",
                {"Id": 39306112, "Status": "FinishedMonitored"},
            )
            # Focus becomes None (one notify). Finish with no remaining
            # focus also refreshes the ride list (second notify).
            assert hits == [1, 1]
        finally:
            await coordinator.async_stop()
