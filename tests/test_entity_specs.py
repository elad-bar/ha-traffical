"""HA-free entity catalog: gating, value resolution and availability."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.traffical.common.helpers import entity_object_id
from custom_components.traffical.models.entity_specs import (
    ENTITY_SPECS,
    SCOPE_HUB,
    SCOPE_RIDE,
    get_entity_specs,
    spec_as_dict,
)
from custom_components.traffical.models.entity_values import (
    EntityContext,
    EntityValueResolver,
    child_id_for_label,
)

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "traffical"

_STATIONS = [
    {
        "stationId": "s1",
        "name": "Main st 5",
        "address": "Main st 5",
        "lat": 32.1,
        "lng": 34.8,
    },
    {
        "stationId": "s2",
        "name": "School",
        "address": "School rd 1",
        "isTarget": True,
        "lat": 32.2,
        "lng": 34.9,
        "actualArriveDateTime": "2026-09-03T05:10:00Z",
    },
]

_RIDE = {
    "key": "1:0",
    "status": "New",
    "ride_id": 7,
    "ticket": "t-7",
    "assigned_today": True,
    "checkin": {"checkIn": None},
    "list_row": {
        "rideInfo": {
            "passengerStationName": "Main st 5",
            "passengerDestinationName": "School",
            "passengerStationArrivalDateTime": "2026-09-03T05:40:00Z",
            "passengerDestinationArrivalDateTime": "2026-09-03T06:10:00Z",
            "shuttleCompany": "Co",
        }
    },
    "details": {
        "carNumber": "12-345-67",
        "carTypeId": 3,
        "shuttleCompanyName": "Co",
        "driver": {"name": "Dan"},
        "stations": _STATIONS,
    },
    "lat": None,
    "lng": None,
    "passed_stations": set(),
}

_CTX = EntityContext(
    member_id=10,
    session_ok=True,
    children=(),
    policies={"gotOnRideReport": {"isActive": True}},
    focus={"name": "Line 1", "ride_id": 7, "ticket": "t-7", "status": "New"},
    focus_ride_key="1:0",
    passenger_name="Kid One",
)


def _spec(key: str):
    for spec in ENTITY_SPECS:
        if spec.key == key:
            return spec
    raise AssertionError(f"no spec for {key}")


def _station_state(station_id: str) -> dict:
    return {"ride": _RIDE, "ride_key": "1:0", "station_id": station_id}


@pytest.mark.parametrize(
    ("key", "ride_key", "station_id", "expected"),
    [
        ("next_ride", None, None, "traffical_next_ride"),
        ("status", "392681:120", None, "traffical_392681_120_status"),
        ("stop", "392681:120", "34838", "traffical_392681_120_stop_34838"),
        ("rides", "392681:120", None, "traffical_392681_120_rides"),
    ],
)
def test_entity_object_id_uses_route_and_station_ids(
    key: str, ride_key: str | None, station_id: str | None, expected: str
) -> None:
    assert entity_object_id(key, ride_key, station_id) == expected


def test_catalog_keys_are_unique_per_platform() -> None:
    seen = {(spec.platform, spec.key) for spec in ENTITY_SPECS}
    assert len(seen) == len(ENTITY_SPECS)


def test_every_spec_key_has_an_english_name() -> None:
    strings = json.loads((_ROOT / "strings.json").read_text(encoding="utf-8"))
    entities = strings["entity"]
    for spec in ENTITY_SPECS:
        if spec.dynamic_name:
            continue
        platform = entities.get(spec.platform) or {}
        assert spec.key in platform, f"{spec.platform}.{spec.key} missing in strings"
        assert platform[spec.key].get("name")


def test_specs_filter_by_platform_and_scope() -> None:
    hub_sensors = get_entity_specs("sensor", scope=SCOPE_HUB)
    assert [spec.key for spec in hub_sensors] == ["next_ride"]
    assert [spec.key for spec in get_entity_specs("calendar", scope=SCOPE_HUB)] == []
    assert [spec.key for spec in get_entity_specs("calendar", scope=SCOPE_RIDE)] == [
        "rides"
    ]
    ride_sensors = {spec.key for spec in get_entity_specs("sensor", scope=SCOPE_RIDE)}
    assert ride_sensors == {
        "status",
        "my_station",
        "destination",
        "driver",
        "vehicle",
        "boarding_at",
        "dropoff_at",
    }


def test_policy_gate_hides_report_buttons() -> None:
    without = {spec.key for spec in get_entity_specs("button", caps={})}
    assert without == {"refresh"}
    with_policy = {
        spec.key
        for spec in get_entity_specs(
            "button",
            caps={
                "policies": {
                    "gotOnRideReport": {"isActive": True},
                    "notComingReport": {"isActive": False},
                }
            },
        )
    }
    assert with_policy == {"refresh", "check_in", "check_out"}


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("status", "New"),
        ("my_station", "Main st 5"),
        ("destination", "School"),
        ("driver", "Dan"),
        ("vehicle", "12-345-67"),
        ("checked_in", None),
    ],
)
def test_ride_values_resolve(key: str, expected) -> None:
    resolver = EntityValueResolver()
    assert resolver.resolve_value(_spec(key), _RIDE, _CTX) == expected


def test_hub_value_and_attributes_use_focus() -> None:
    resolver = EntityValueResolver()
    spec = _spec("next_ride")
    assert resolver.resolve_value(spec, {}, _CTX) == "Line 1"
    attrs = resolver.resolve_attributes(spec, {}, _CTX)
    assert attrs["ride_id"] == 7
    assert attrs["ticket"] == "t-7"


def test_ride_attributes_resolve() -> None:
    resolver = EntityValueResolver()
    assert resolver.resolve_attributes(_spec("status"), _RIDE, _CTX) == {
        "ride_id": 7,
        "ticket": "t-7",
    }
    assert resolver.resolve_attributes(_spec("vehicle"), _RIDE, _CTX) == {
        "type": 3,
        "shuttle_company": "Co",
    }
    my_station = resolver.resolve_attributes(_spec("my_station"), _RIDE, _CTX)
    assert my_station["name"] == "Main st 5"
    assert my_station["arrival"] == "2026-09-03T05:40:00+00:00"
    dest = resolver.resolve_attributes(_spec("destination"), _RIDE, _CTX)
    assert dest["address"] == "School rd 1"
    assert dest["arrival"] == "2026-09-03T06:10:00+00:00"
    assert resolver.resolve_value(_spec("boarding_at"), _RIDE, _CTX).hour == 5
    assert resolver.resolve_value(_spec("dropoff_at"), _RIDE, _CTX).hour == 6


def test_availability_rules() -> None:
    resolver = EntityValueResolver()
    assert resolver.is_available(_spec("check_in"), _RIDE, _CTX)
    assert not resolver.is_available(_spec("check_out"), _RIDE, _CTX)
    assert resolver.is_available(_spec("not_coming"), _RIDE, _CTX)
    assert not resolver.is_available(_spec("bus"), _RIDE, _CTX)
    assert not resolver.is_available(_spec("child"), {}, _CTX)


def test_availability_needs_session_and_assignment() -> None:
    resolver = EntityValueResolver()
    spec = _spec("status")
    assert resolver.is_available(spec, _RIDE, _CTX)
    assert not resolver.is_available(spec, _RIDE, EntityContext(session_ok=False))
    unassigned = {**_RIDE, "assigned_today": False}
    assert not resolver.is_available(spec, unassigned, _CTX)


def test_checked_in_flips_check_buttons() -> None:
    resolver = EntityValueResolver()
    checked = {**_RIDE, "status": "Ongoing", "checkin": {"checkIn": True}}
    assert resolver.resolve_value(_spec("checked_in"), checked, _CTX) is True
    assert not resolver.is_available(_spec("check_in"), checked, _CTX)
    assert resolver.is_available(_spec("check_out"), checked, _CTX)


def test_bus_position_needs_live_gps() -> None:
    resolver = EntityValueResolver()
    spec = _spec("bus")
    live = {**_RIDE, "status": "OngoingMonitored", "lat": 32.05, "lng": 34.77}
    assert resolver.is_available(spec, live, _CTX)
    assert resolver.resolve_value(spec, live, _CTX) == (32.05, 34.77)


def test_station_name_icon_and_kind() -> None:
    resolver = EntityValueResolver()
    spec = _spec("stop")
    home = _station_state("s1")
    target = _station_state("s2")
    assert resolver.resolve_name(spec, home, _CTX) == "Main st 5"
    assert resolver.resolve_icon(spec, home, _CTX) == "mdi:home"
    assert resolver.resolve_attributes(spec, home, _CTX)["kind"] == "home"
    assert resolver.resolve_name(spec, target, _CTX) == "School"
    assert resolver.resolve_icon(spec, target, _CTX) == "mdi:school"
    assert resolver.resolve_attributes(spec, target, _CTX)["kind"] == "target"
    assert resolver.resolve_value(spec, target, _CTX) == (32.2, 34.9)
    live = {
        **_RIDE,
        "lat": 32.1,
        "lng": 34.8,
    }
    attrs = resolver.resolve_attributes(
        spec, {"ride": live, "ride_key": "1:0", "station_id": "s1"}, _CTX
    )
    assert attrs["distance_m"] == 0
    assert resolver.resolve_attributes(spec, home, _CTX)["distance_m"] is None


def test_afternoon_destination_and_single_home_icon() -> None:
    ride = {
        "key": "428988:121",
        "status": "New",
        "assigned_today": True,
        "list_row": {
            "rideInfo": {
                "passengerStationName": "חקלאי הכפר הירוק - רמת השרון",
                "passengerDestinationName": "השומרון 11, קדימה-צורן, ישראל",
            }
        },
        "details": {
            "stations": [
                {
                    "stationId": "school",
                    "name": "חקלאי הכפר הירוק - רמת השרון",
                    "address": "הכפר הירוק, רמת השרון, ישראל",
                    "isTarget": True,
                    "lat": 32.13,
                    "lng": 34.83,
                },
                {
                    "stationId": "home",
                    "name": "השומרון 11, קדימה-צורן, ישראל",
                    "address": "הרצוג 7, קדימה-צורן, ישראל",
                    "lat": 32.28,
                    "lng": 34.91,
                    "passengers": [{"id": 551070}],
                },
            ]
        },
        "passed_stations": set(),
    }
    ctx = EntityContext(member_id=551070, session_ok=True, focus_ride_key="428988:121")
    resolver = EntityValueResolver()

    assert resolver.resolve_value(_spec("my_station"), ride, ctx) == (
        "הכפר הירוק, רמת השרון, ישראל"
    )
    assert resolver.resolve_value(_spec("destination"), ride, ctx) == (
        "הרצוג 7, קדימה-צורן, ישראל"
    )
    school = {"ride": ride, "ride_key": "428988:121", "station_id": "school"}
    house = {"ride": ride, "ride_key": "428988:121", "station_id": "home"}
    assert resolver.resolve_attributes(_spec("stop"), school, ctx)["kind"] == "target"
    assert resolver.resolve_attributes(_spec("stop"), house, ctx)["kind"] == "home"
    assert resolver.resolve_icon(_spec("stop"), house, ctx) == "mdi:home"
    assert resolver.resolve_icon(_spec("stop"), school, ctx) == "mdi:school"


def test_station_only_available_on_the_focused_ride() -> None:
    resolver = EntityValueResolver()
    spec = _spec("stop")
    assert resolver.is_available(spec, _station_state("s1"), _CTX)
    other = {**_station_state("s1"), "ride_key": "9:1"}
    assert not resolver.is_available(spec, other, _CTX)


def test_child_options_and_reverse_lookup() -> None:
    resolver = EntityValueResolver()
    spec = _spec("child")
    ctx = EntityContext(
        member_id=10,
        session_ok=True,
        children=(
            {"memberId": 10, "firstName": "Kid", "lastName": "One"},
            {"memberId": 11, "firstName": "Kid", "lastName": "Two"},
        ),
    )
    assert resolver.resolve_options(spec, {}, ctx) == ["Kid One", "Kid Two"]
    assert resolver.resolve_value(spec, {}, ctx) == "Kid One"
    assert resolver.is_available(spec, {}, ctx)
    assert child_id_for_label("Kid Two", ctx) == "11"
    assert child_id_for_label("Nobody", ctx) is None


def test_child_options_fall_back_to_the_passenger() -> None:
    resolver = EntityValueResolver()
    spec = _spec("child")
    assert resolver.resolve_options(spec, {}, _CTX) == ["Kid One"]
    assert resolver.resolve_value(spec, {}, _CTX) == "Kid One"


def test_spec_as_dict_is_serialisable() -> None:
    payload = spec_as_dict(_spec("status"))
    assert payload["key"] == "status"
    assert json.dumps(payload)
