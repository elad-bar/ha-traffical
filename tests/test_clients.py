"""HA-free REST / SignalR / store tests."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from custom_components.traffical.common.helpers import create_pkce, mask_phone
from custom_components.traffical.managers.api_client import ApiClient
from custom_components.traffical.managers.identity_client import IdentityClient
from custom_components.traffical.managers.mobile_client import MobileClient
from custom_components.traffical.managers.signalr_client import (
    SignalRHubs,
    _parse_hub_args,
)
from custom_components.traffical.managers.store import SessionStore
from custom_components.traffical.models.coordinates import MonitoredPath, haversine_m
from custom_components.traffical.models.rides import (
    Ride,
    focus_ride_key,
    ride_device_key,
    rides_customer_type,
    status_live,
)
from custom_components.traffical.models.stations import Station, station_event_id


def test_ride_device_key_stable() -> None:
    assert ride_device_key(392681, 120) == "392681:120"
    assert ride_device_key("x", 1) is None


def test_customer_type_municipality() -> None:
    assert rides_customer_type(28) == "Municipality"
    assert rides_customer_type(None) == "Municipality"


def test_status_live() -> None:
    assert status_live("OngoingMonitored")
    assert not status_live("New")


def test_focus_ride_key_live_beats_finished() -> None:
    rides = {
        "392681:120": {
            "assigned_today": True,
            "status": "FinishedMonitored",
            "details": {"startTime": "2026-09-02T05:00:00Z"},
        },
        "428988:121": {
            "assigned_today": True,
            "status": "Ongoing",
            "details": {"startTime": "2026-09-02T13:00:00Z"},
        },
    }
    assert focus_ride_key(rides) == "428988:121"


def test_focus_ride_key_next_unfinished() -> None:
    rides = {
        "392681:120": {
            "assigned_today": True,
            "status": "Finished",
            "details": {"startTime": "2026-09-02T05:00:00Z"},
        },
        "428988:121": {
            "assigned_today": True,
            "status": "New",
            "details": {"startTime": "2026-09-02T13:00:00Z"},
        },
    }
    assert focus_ride_key(rides) == "428988:121"


def test_focus_ride_key_all_finished() -> None:
    rides = {
        "392681:120": {
            "assigned_today": True,
            "status": "FinishedMonitored",
            "details": {"startTime": "2026-09-02T05:00:00Z"},
        }
    }
    assert focus_ride_key(rides) is None


def test_pkce_and_mask() -> None:
    verifier, challenge = create_pkce()
    assert verifier
    assert challenge
    assert mask_phone("0501234567") == "***4567"


def test_parse_hub_json_string() -> None:
    parsed = _parse_hub_args(['{"stationId": 1}'])
    assert parsed == {"stationId": 1}


@pytest.mark.asyncio
async def test_mobile_hub_decodes_json_string_event() -> None:
    received: list[tuple[str, object]] = []

    async def on_event(event: str, payload: object) -> None:
        received.append((event, payload))

    hubs = SignalRHubs(
        object(),  # type: ignore[arg-type]
        "https://api.example",
        lambda: {"access_token": "token"},
    )
    hubs._mobile_on_event = on_event

    await hubs._handle_mobile_text(
        json.dumps(
            {
                "type": 1,
                "target": "UpdateRideStatus",
                "arguments": ['{"Id":39306112,"Status":"OngoingMonitored"}'],
            }
        )
        + "\x1e"
    )

    assert received == [
        (
            "UpdateRideStatus",
            {"Id": 39306112, "Status": "OngoingMonitored"},
        )
    ]


class _ClosedNegotiate:
    async def __aenter__(self):
        raise RuntimeError("Session is closed")

    async def __aexit__(self, *args):
        return False


class _ClosingSession:
    def __init__(self) -> None:
        self.closed = False
        self.posts = 0

    def post(self, url, **kwargs):
        self.posts += 1
        return _ClosedNegotiate()


@pytest.mark.asyncio
async def test_start_mobile_skips_closed_session() -> None:
    session = _ClosingSession()
    session.closed = True
    hubs = SignalRHubs(
        session,  # type: ignore[arg-type]
        "https://api.example",
        lambda: {"access_token": "token"},
    )
    await hubs.start_mobile(lambda *_: None)
    assert hubs._mobile_task is None
    assert session.posts == 0


@pytest.mark.asyncio
async def test_mobile_hub_exits_when_session_closed() -> None:
    session = _ClosingSession()
    hubs = SignalRHubs(
        session,  # type: ignore[arg-type]
        "https://api.example",
        lambda: {"access_token": "token"},
    )
    with patch(
        "custom_components.traffical.managers.signalr_client.HUB_RECONNECT_S",
        0,
    ):
        await hubs.start_mobile(lambda *_: None)
        task = hubs._mobile_task
        assert task is not None
        await asyncio.wait_for(task, 1)
    assert task.done()
    assert session.posts == 1


def test_haversine_zero_and_known_span() -> None:
    assert haversine_m(32.1, 34.8, 32.1, 34.8) == 0
    metres = haversine_m(32.1, 34.8, 32.2, 34.9)
    assert 14000 < metres < 16000


def test_monitored_path_accepts_live_pascal_case_point() -> None:
    payload = {
        "Latitude": 32.12,
        "Longitude": 34.8,
        "LocatedAt": "2026-09-02T07:14:03",
        "SourceType": 2,
    }

    assert MonitoredPath(payload).points == [payload]


def test_monitored_path_ignores_live_passenger_point() -> None:
    payload = {
        "Latitude": 32.12,
        "Longitude": 34.8,
        "LocatedAt": "2026-09-02T07:14:03",
        "SourceType": 3,
    }

    assert MonitoredPath(payload).points == []


def test_monitored_path_unwraps_monitoring_path_groups() -> None:
    driver_point = {
        "latitude": 32.12,
        "longitude": 34.8,
        "locatedAt": "2026-09-02T07:14:03",
    }
    passenger_point = {
        "latitude": 32.13,
        "longitude": 34.81,
        "locatedAt": "2026-09-02T07:14:18",
    }
    payload = [
        {"memberId": 1, "sourceType": 2, "coordinates": [driver_point]},
        {"memberId": 2, "sourceType": 3, "coordinates": [passenger_point]},
    ]
    path = MonitoredPath(payload)

    assert path.points == [driver_point]
    assert path.latest == driver_point
    assert path.sources == ["2:1:1", "3:2:1"]


def test_station_event_id_accepts_pascal_case() -> None:
    assert station_event_id({"StationId": 98765}) == "98765"


def test_station_label_prefers_address_and_target_name() -> None:
    stop = Station({"stationId": 1, "name": "Dispatcher label", "address": "1 Main"})
    target = Station(
        {"stationId": 2, "name": "School", "address": "2 School", "isTarget": True}
    )

    assert stop.label == "1 Main"
    assert target.label == "School"


def test_station_is_yours_by_name_or_membership() -> None:
    by_name = Station({"name": "Home"})
    by_member = Station({"name": "Other", "passengers": [{"id": 10}]})

    assert by_name.is_yours("Home", None)
    assert by_member.is_yours("Home", 10)
    assert not by_member.is_yours("Home", 11)


def test_ride_reads_key_ticket_and_status_from_row_and_details() -> None:
    row = {
        "status": "New",
        "rideInfo": {
            "rideId": 39306112,
            "rideTicket": "t1",
            "routeId": 392681,
            "direction": 120,
            "passengerStationName": "Home",
        },
    }
    details = {"status": "OngoingMonitored", "name": "Morning", "stations": [{"id": 1}]}
    ride = Ride(row, details)

    assert ride.key == "392681:120"
    assert ride.ticket == "t1"
    assert ride.ride_id == 39306112
    assert ride.name == "Morning"
    assert ride.status == "OngoingMonitored"
    assert ride.is_live
    assert ride.passenger_stop == "Home"
    assert len(ride.stations) == 1


def test_ride_from_cache_round_trips() -> None:
    record = {
        "list_row": {"rideInfo": {"routeId": 1, "direction": 2}},
        "details": {"name": "Afternoon"},
    }

    assert Ride.from_cache(record).key == "1:2"
    assert Ride.from_cache(record).name == "Afternoon"
    assert Ride.from_cache(None).key is None


def test_ride_device_name_afternoon_uses_addresses_not_is_target() -> None:
    row = {
        "name": "צורן /קדימה-רציף בשטח היסעים:12",
        "rideInfo": {
            "routeId": 428988,
            "direction": 121,
            "passengerStationName": "חקלאי הכפר הירוק - רמת השרון",
            "passengerDestinationName": "השומרון 11, קדימה-צורן, ישראל",
        },
    }
    details = {
        "stations": [
            {
                "name": "חקלאי הכפר הירוק - רמת השרון",
                "address": "הכפר הירוק, רמת השרון, ישראל",
                "isTarget": True,
            },
            {
                "name": "השומרון 11, קדימה-צורן, ישראל",
                "address": "הרצוג 7, קדימה-צורן, ישראל",
                "isTarget": False,
            },
        ]
    }
    ride = Ride(row, details)

    assert ride.passenger_destination == "השומרון 11, קדימה-צורן, ישראל"
    assert ride.target_station() is not None
    assert ride.target_station().address == "הכפר הירוק, רמת השרון, ישראל"
    assert ride.device_name() == (
        "Traffical הכפר הירוק, רמת השרון, ישראל - הרצוג 7, קדימה-צורן, ישראל"
    )


def test_ride_device_name_morning_home_to_school() -> None:
    row = {
        "rideInfo": {
            "passengerStationName": "השומרון 11, קדימה-צורן, ישראל",
            "passengerDestinationName": "חקלאי הכפר הירוק - רמת השרון",
        }
    }
    details = {
        "stations": [
            {
                "name": "השומרון 11, קדימה-צורן, ישראל",
                "address": "הרצוג 9, קדימה-צורן, ישראל",
            },
            {
                "name": "חקלאי הכפר הירוק - רמת השרון",
                "address": "הכפר הירוק, רמת השרון, ישראל",
                "isTarget": True,
            },
        ]
    }

    assert Ride(row, details).device_name() == (
        "Traffical הרצוג 9, קדימה-צורן, ישראל - הכפר הירוק, רמת השרון, ישראל"
    )


def test_home_station_afternoon_prefers_passenger_assignment() -> None:
    row = {
        "rideInfo": {
            "passengerStationName": "חקלאי הכפר הירוק - רמת השרון",
            "passengerDestinationName": "השומרון 11, קדימה-צורן, ישראל",
        }
    }
    details = {
        "stations": [
            {
                "id": 244399823,
                "name": "חקלאי הכפר הירוק - רמת השרון",
                "address": "הכפר הירוק, רמת השרון, ישראל",
                "isTarget": True,
            },
            {
                "id": 244399826,
                "name": "השומרון 11, קדימה-צורן, ישראל",
                "address": "הרצוג 7, קדימה-צורן, ישראל",
                "passengers": [{"id": 551070}],
            },
        ]
    }
    ride = Ride(row, details)

    home = ride.home_station(551070)
    assert home is not None
    assert home.address == "הרצוג 7, קדימה-צורן, ישראל"
    assert ride.dropoff_station() is not None
    assert ride.dropoff_station().name == "השומרון 11, קדימה-צורן, ישראל"
    assert ride.boarding_station() is not None
    assert ride.boarding_station().is_target
    assert ride.your_station(551070) is not None
    assert ride.your_station(551070).is_target


def test_home_station_morning_is_boarding() -> None:
    row = {
        "rideInfo": {
            "passengerStationName": "השומרון 11, קדימה-צורן, ישראל",
            "passengerDestinationName": "חקלאי הכפר הירוק - רמת השרון",
        }
    }
    details = {
        "stations": [
            {
                "id": 1,
                "name": "השומרון 11, קדימה-צורן, ישראל",
                "address": "הרצוג 9, קדימה-צורן, ישראל",
            },
            {
                "id": 2,
                "name": "חקלאי הכפר הירוק - רמת השרון",
                "address": "הכפר הירוק, רמת השרון, ישראל",
                "isTarget": True,
            },
        ]
    }
    ride = Ride(row, details)

    home = ride.home_station(None)
    assert home is not None
    assert home.address == "הרצוג 9, קדימה-צורן, ישראל"


def test_ride_device_name_empty_without_station_addresses() -> None:
    row = {
        "name": "Line",
        "rideInfo": {
            "passengerStationName": "Home",
            "passengerDestinationName": "School",
        },
    }

    assert Ride(row, {"name": "Line"}).device_name() == ""
    assert Ride(row, {"name": "Line"}).device_name() or row["name"] == "Line"


def test_store_tokens(tmp_path) -> None:
    store = SessionStore(tmp_path / "config.json")
    store.apply_live_hosts()
    store.set_tokens({"access_token": "a", "refresh_token": "r", "expires_in": 60})
    store.save()
    other = SessionStore(tmp_path / "config.json")
    other.load()
    assert other.tokens["access_token"] == "a"
    assert other.device_id


class _FakeResp:
    def __init__(
        self, status: int, payload: object, headers: dict | None = None
    ) -> None:
        self.status = status
        self._payload = payload
        self.headers = headers or {}
        self.content_type = "application/json"

    async def text(self) -> str:
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)

    async def json(self, content_type=None):
        return self._payload

    async def read(self) -> bytes:
        return (await self.text()).encode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, resp: _FakeResp) -> None:
        self.resp = resp
        self.calls: list[tuple] = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.resp

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.resp


@pytest.mark.asyncio
async def test_identity_request_otp() -> None:
    resp = _FakeResp(200, {"expiredIn": 90}, headers={"x-otp-ticket": "ticket-1"})
    session = _FakeSession(resp)
    client = IdentityClient("https://id.example", session)  # type: ignore[arg-type]
    ticket, expired = await client.request_otp("0500000000")
    assert ticket == "ticket-1"
    assert expired == 90


@pytest.mark.asyncio
async def test_mobile_list_rides() -> None:
    resp = _FakeResp(200, [{"rideId": 1}])
    session = _FakeSession(resp)
    client = MobileClient("https://api.example", session)  # type: ignore[arg-type]
    data = await client.list_rides("Municipality", "2026-09-02")
    assert data == [{"rideId": 1}]
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert "Rides/Municipality" in url
    log = client.query_log_for_diagnostics()
    key = next(iter(log["account"]))
    assert "list_rides" in key
    assert log["account"][key]["request"]["http_status"] == 200
    assert log["account"][key]["shape"]["count"] == 1
    assert log["rides"] == {}


@pytest.mark.asyncio
async def test_api_client_query_log_skips_token_and_records_failures() -> None:
    resp = _FakeResp(500, "nope")
    session = _FakeSession(resp)
    client = ApiClient("https://api.example", session)  # type: ignore[arg-type]
    with pytest.raises(Exception):
        await client.get("/x", action="x")
    log = client.query_log_for_diagnostics()
    key = next(iter(log["account"]))
    assert log["account"][key]["request"]["http_status"] == 500
    assert log["account"][key]["request"]["error"]

    token_resp = _FakeResp(200, {"access_token": "tokensecret", "refresh_token": "r"})
    identity = IdentityClient("https://id.example", _FakeSession(token_resp))
    body = await identity.refresh("refreshsecret")
    assert body["access_token"] == "tokensecret"
    token_log = identity.query_log_for_diagnostics()
    assert token_log["account"] == {}
    assert "tokensecret" not in str(token_log)


@pytest.mark.asyncio
async def test_api_client_query_log_scopes_ride_id() -> None:
    resp = _FakeResp(200, {"ok": True})
    client = MobileClient(
        "https://api.example", _FakeSession(resp)
    )  # type: ignore[arg-type]
    await client.check_in_passenger(39306112, 10, True)
    log = client.query_log_for_diagnostics(39306112)
    assert "39306112" in log["rides"]
    assert any("checkin_passenger" in key for key in log["rides"]["39306112"])


@pytest.mark.asyncio
async def test_userinfo_query_log_has_no_profile_shape() -> None:
    resp = _FakeResp(200, {"sub": "user-sub-1", "phone": "0501234567"})
    identity = IdentityClient("https://id.example", _FakeSession(resp))
    await identity.userinfo()
    log = identity.query_log_for_diagnostics()
    record = next(iter(log["account"].values()))
    assert record["request"]["http_status"] == 200
    assert record["shape"] is None
    assert "0501234567" not in str(log)


def test_signalr_snapshot_has_both_hubs_without_gps() -> None:
    hubs = SignalRHubs(
        object(),  # type: ignore[arg-type]
        "https://api.example",
        lambda: {"access_token": "token"},
    )
    hubs.track_ride_id = 39306112
    hubs._frames = {"invocation:ReceiveCoordinates": 2}
    hubs._mobile_frames = {"invocation:UpdateRideStatus": 1}
    hubs._dashboard_diag = {"last_event": "ReceiveCoordinates"}
    hubs._mobile_diag = {"last_event": "UpdateRideStatus"}
    snap = hubs.snapshot_for_diagnostics()
    blob = str(snap)
    assert snap["dashboard"]["track_ride_id"] == 39306112
    assert snap["dashboard"]["last_event"] == "ReceiveCoordinates"
    assert snap["mobile"]["last_event"] == "UpdateRideStatus"
    assert snap["dashboard"]["ws_open"] is False
    assert "token" not in blob
    assert "lat" not in blob
    assert "32." not in blob
