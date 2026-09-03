"""Diagnostics redaction and payload tests."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.traffical.common.consts import (
    CONF_PHONE,
    CONF_POLL_INTERVAL,
    CONF_TOKENS,
    DOMAIN,
)
from custom_components.traffical.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

_RIDE_KEY = "392681:120"


def _query_log(ride_id=None):
    account = {
        "POST /api/Mobile/Rides/Municipality (list_rides)": {
            "request": {
                "http_status": 200,
                "error": None,
            },
            "shape": {"kind": "list", "count": 1},
        }
    }
    per = {
        "39306112": {
            "POST /api/Mobile/CheckIn/Passenger (checkin_passenger)": {
                "request": {"http_status": 200, "error": None},
                "shape": {"kind": "object", "keys": []},
            }
        }
    }
    if ride_id is not None:
        rid = str(ride_id)
        return {"account": account, "rides": {rid: per.get(rid, {})}}
    return {"account": account, "rides": per}


def _mock_entry_and_coordinator():
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user-sub-1",
        data={
            CONF_PHONE: "0501234567",
            "environment": "Live",
            CONF_TOKENS: {
                "access_token": "tokensecret",
                "refresh_token": "refreshsecret",
            },
        },
        options={CONF_POLL_INTERVAL: 45},
        title="Traffical",
    )
    coordinator = MagicMock()
    coordinator.hub_id = "user-sub-1"
    coordinator.ride_keys = [_RIDE_KEY]
    coordinator._reauth_started = False
    coordinator.last_update_success = True
    coordinator.last_exception = None
    coordinator.update_interval = timedelta(seconds=45)
    coordinator.member_id.return_value = 10
    coordinator.policy_active.return_value = True
    coordinator.store.user = {
        "sub": "user-sub-1",
        "person": {"memberId": 10, "firstName": "SecretChild"},
        "customer": {"type": 28},
    }
    coordinator.store.environment = "Live"
    coordinator.store.api_url = "https://api.example"
    coordinator.store.identity_url = "https://id.example"
    coordinator.store.language = "he"
    coordinator.store.device_id = "dev-1"
    coordinator.store.child_id = "99"
    coordinator.store.tokens = {
        "access_token": "tokensecret",
        "refresh_token": "refreshsecret",
        "expires_in": 3600,
        "obtained_at": "2026-09-02T10:00:00+00:00",
    }
    coordinator.data = {
        "session_ok": True,
        "live_key": _RIDE_KEY,
        "focus_ride_key": _RIDE_KEY,
        "children": [{"memberId": 10, "name": "SecretChild"}],
        "policies": {"checkIn": {"isActive": True}},
        "rides": {
            _RIDE_KEY: {
                "key": _RIDE_KEY,
                "route_id": 392681,
                "direction": 120,
                "ride_id": 39306112,
                "ticket": "ticket-secret",
                "status": "OngoingMonitored",
                "assigned_today": True,
                "lat": 32.12,
                "lng": 34.8,
                "passed_stations": {"1"},
                "approaching_fired": False,
                "checkin": {"checkIn": True, "checkInAt": "2026-09-02T07:00:00Z"},
                "list_row": {},
                "details": {
                    "startTime": "2026-09-02T06:30:00Z",
                    "stations": [{"id": 1, "name": "Home", "address": "1 Secret St"}],
                },
            }
        },
    }
    coordinator.ride.side_effect = lambda key: coordinator.data["rides"].get(key) or {}
    coordinator.identity.query_log_for_diagnostics.side_effect = _query_log
    coordinator.mobile.query_log_for_diagnostics.side_effect = _query_log
    coordinator.hubs.snapshot_for_diagnostics.return_value = {
        "dashboard": {
            "track_ride_id": 39306112,
            "ws_open": True,
            "task_running": True,
            "last_event": "ReceiveCoordinates",
            "frames": {"invocation:ReceiveCoordinates": 3},
        },
        "mobile": {
            "ws_open": True,
            "task_running": True,
            "last_event": "UpdateRideStatus",
            "frames": {"invocation:UpdateRideStatus": 1},
        },
    }
    entry.runtime_data = coordinator
    return entry, coordinator


@pytest.mark.asyncio
async def test_diagnostics_redacts_secrets() -> None:
    entry, _coordinator = _mock_entry_and_coordinator()

    diag = await async_get_config_entry_diagnostics(None, entry)
    blob = str(diag)

    assert "tokensecret" not in blob
    assert "refreshsecret" not in blob
    assert "0501234567" not in blob
    assert "ticket-secret" not in blob
    assert "SecretChild" not in blob
    assert "32.12" not in blob
    assert "34.8" not in blob
    assert "1 Secret St" not in blob
    assert diag["entry"]["options"][CONF_POLL_INTERVAL] == 45
    assert diag["store"]["access_token_present"] is True
    assert diag["store"]["refresh_token_present"] is True
    assert "tokens" not in diag["store"]
    assert diag["account"]["details"]["session_ok"] is True
    assert diag["account"]["details"]["customer_type"] == "Municipality"
    assert "list_rides" in str(diag["account"]["api"])
    assert "dashboard" in diag["account"]["signalr"]
    assert "mobile" in diag["account"]["signalr"]
    ride = diag["rides"][_RIDE_KEY]
    assert ride["details"]["has_fix"] is True
    assert ride["details"]["ticket_present"] is True
    assert ride["details"]["check_in"] is True
    assert ride["details"]["is_live"] is True
    assert "checkin_passenger" in str(ride["api"])
    assert "list_row" not in ride
    assert ride["details"].get("lat") is None


@pytest.mark.asyncio
async def test_device_diagnostics_scopes_ride() -> None:
    entry, _coordinator = _mock_entry_and_coordinator()
    device = MagicMock()
    device.identifiers = {(DOMAIN, f"user-sub-1:{_RIDE_KEY}")}

    diag = await async_get_device_diagnostics(None, entry, device)

    assert set(diag["rides"]) == {_RIDE_KEY}
    assert diag["account"]["signalr"]["dashboard"]["track_ride_id"] == 39306112
    assert "tokensecret" not in str(diag)


@pytest.mark.asyncio
async def test_device_diagnostics_unknown_device() -> None:
    entry, _coordinator = _mock_entry_and_coordinator()
    device = MagicMock()
    device.identifiers = {(DOMAIN, "other-id")}

    diag = await async_get_device_diagnostics(None, entry, device)
    assert diag == {"error": "unknown_device"}


@pytest.mark.asyncio
async def test_diagnostics_missing_runtime() -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_PHONE: "0501234567"})
    diag = await async_get_config_entry_diagnostics(None, entry)
    assert "entry" in diag
    assert "rides" not in diag
    assert "0501234567" not in str(diag)
