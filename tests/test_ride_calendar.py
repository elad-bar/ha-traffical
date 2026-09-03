"""HA-free ride calendar: listed today plus next day per line."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from custom_components.traffical.common.helpers import parse_utc
from custom_components.traffical.models.ride_calendar import (
    current_event,
    events_for_line,
    items_from_occurrence,
)
from custom_components.traffical.models.rides import Ride

_ISRAEL = ZoneInfo("Asia/Jerusalem")


def _morning(service_date: str, **kwargs):
    row = {
        "name": "Morning line",
        "rideInfo": {
            "routeId": 392681,
            "direction": 120,
            "startDateTime": f"{service_date}T06:30:00",
            "endDateTime": f"{service_date}T07:20:00",
            "passengerStationName": "Home",
            "passengerStationArrivalDateTime": f"{service_date}T06:45:00",
            "passengerDestinationName": "School",
            "passengerDestinationArrivalDateTime": f"{service_date}T07:12:00",
        },
    }
    details = {
        "name": "Morning line",
        "startTime": f"{service_date}T06:30:00",
        "endTime": f"{service_date}T07:20:00",
        "status": "New",
        "stations": [
            {
                "name": "Home",
                "address": "1 Home",
                "arrivalTime": f"{service_date}T06:45:00",
                "actualArriveDateTime": None,
            },
            {
                "name": "School",
                "address": "2 School",
                "isTarget": True,
                "arrivalTime": f"{service_date}T07:12:00",
                "actualArriveDateTime": f"{service_date}T07:15:00",
            },
        ],
    }
    occ = Ride(row, details).occurrence(service_date)
    assert occ is not None
    occ.update(kwargs)
    return occ


def _afternoon(service_date: str):
    row = {
        "name": "Afternoon",
        "rideInfo": {
            "routeId": 428988,
            "direction": 121,
            "startDateTime": f"{service_date}T16:30:00",
            "endDateTime": f"{service_date}T17:18:00",
            "passengerStationName": "School",
            "passengerStationArrivalDateTime": f"{service_date}T16:30:00",
            "passengerDestinationName": "Home",
            "passengerDestinationArrivalDateTime": f"{service_date}T17:00:00",
        },
    }
    details = {
        "name": "Afternoon",
        "startTime": f"{service_date}T16:30:00",
        "endTime": f"{service_date}T17:18:00",
        "status": "New",
        "stations": [
            {
                "name": "School",
                "address": "2 School",
                "isTarget": True,
                "arrivalTime": f"{service_date}T16:30:00",
            },
            {
                "name": "Home",
                "address": "1 Home",
                "arrivalTime": f"{service_date}T17:00:00",
            },
        ],
    }
    occ = Ride(row, details).occurrence(service_date)
    assert occ is not None
    return occ


def test_parse_utc_naive_is_israel_z_stays_utc() -> None:
    naive = parse_utc("2026-09-02T16:30:00")
    zulu = parse_utc("2026-09-02T16:30:00Z")
    assert naive is not None and zulu is not None
    assert naive.astimezone(_ISRAEL).hour == 16
    assert zulu.hour == 16
    assert naive != zulu


def test_items_from_occurrence_three_legs() -> None:
    items = items_from_occurrence(_morning("2026-09-02"))
    assert [item.kind for item in items] == ["onboarding", "on_the_way", "eta"]
    assert items[0].uid == "392681:120:2026-09-02:onboarding"
    assert items[0].summary == "Traffical 1 Home - 2 School · Onboarding"
    assert items[0].location == "1 Home"
    assert items[1].location == "2 School"
    assert items[1].summary.endswith(" · On-the-way")
    assert items[2].summary.endswith(" · ETA")
    assert items[2].end == parse_utc("2026-09-02T07:20:00")
    assert "actual 07:15" in items[0].description
    assert items[0].start.astimezone(_ISRAEL).hour == 6
    assert items[0].start.astimezone(_ISRAEL).minute == 30


def test_afternoon_skips_empty_onboarding() -> None:
    items = items_from_occurrence(_afternoon("2026-09-02"))
    assert [item.kind for item in items] == ["on_the_way", "eta"]
    assert items[0].start == parse_utc("2026-09-02T16:30:00")
    assert items[0].end == parse_utc("2026-09-02T17:00:00")
    assert items[1].end == parse_utc("2026-09-02T17:18:00")
    assert items[0].location == "1 Home"


def test_events_for_line_today_and_next_excludes_other_line() -> None:
    occs = [
        _morning("2026-09-02"),
        _morning("2026-09-03"),
        _afternoon("2026-09-02"),
    ]
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 10, tzinfo=timezone.utc)
    days = [
        item.service_date for item in events_for_line(occs, "392681:120", start, end)
    ]
    assert days == ["2026-09-02"] * 3 + ["2026-09-03"] * 3


def test_does_not_invent_events_from_active_days() -> None:
    occ = _morning("2026-09-02")
    occ["list_row"]["activeDays"] = [0, 1, 2, 3, 4]
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 10, tzinfo=timezone.utc)
    days = [
        item.service_date for item in events_for_line([occ], "392681:120", start, end)
    ]
    assert days == ["2026-09-02"] * 3


def test_finished_today_still_emitted() -> None:
    occ = _morning("2026-09-02")
    occ["status"] = "FinishedMonitored"
    occ["details"]["status"] = "FinishedMonitored"
    start = datetime(2026, 9, 2, tzinfo=timezone.utc)
    end = datetime(2026, 9, 3, tzinfo=timezone.utc)
    events = events_for_line([occ], "392681:120", start, end)
    assert [item.kind for item in events] == ["onboarding", "on_the_way", "eta"]
    assert "FinishedMonitored" in events[0].description


def test_current_event_stays_on_unfinished_today() -> None:
    occs = [_morning("2026-09-02"), _morning("2026-09-03")]
    now = datetime(2026, 9, 2, 5, 0, tzinfo=timezone.utc)
    item = current_event(occs, "392681:120", date(2026, 9, 2), now)
    assert item is not None
    assert item.service_date == "2026-09-02"
    assert item.kind == "eta"


def test_current_event_is_onboarding_during_that_leg() -> None:
    occs = [_morning("2026-09-02"), _morning("2026-09-03")]
    now = parse_utc("2026-09-02T06:35:00")
    item = current_event(occs, "392681:120", date(2026, 9, 2), now)
    assert item is not None
    assert item.kind == "onboarding"


def test_current_event_moves_to_next_after_today_finished() -> None:
    today = _morning("2026-09-02")
    today["status"] = "FinishedMonitored"
    today["details"]["status"] = "FinishedMonitored"
    occs = [today, _morning("2026-09-03")]
    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    item = current_event(occs, "392681:120", date(2026, 9, 2), now)
    assert item is not None
    assert item.service_date == "2026-09-03"
    assert item.kind == "onboarding"
