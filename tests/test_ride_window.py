"""HA-free tests for the ride occurrence window."""

from __future__ import annotations

from datetime import date
from typing import Any

from custom_components.traffical.common.consts import RIDES_LOOKAHEAD_DAYS
from custom_components.traffical.models.ride_window import RideWindow

_TODAY = date(2026, 9, 2)


def _row(ride_id: int, status: str, route_id: int = 1, direction: int = 120) -> dict:
    return {
        "status": status,
        "routeId": route_id,
        "direction": direction,
        "rideInfo": {"rideId": ride_id, "routeId": route_id, "direction": direction},
    }


def _entry(
    ride_id: int,
    status: str,
    start: str,
    route_id: int = 1,
    direction: int = 120,
) -> tuple[dict, dict, Any]:
    return (
        _row(ride_id, status, route_id, direction),
        {"status": status, "startTime": start},
        None,
    )


def _window(today: date = _TODAY) -> RideWindow:
    window = RideWindow()
    window.start_day(today)
    return window


def test_dates_span_lookahead() -> None:
    days = _window().dates()
    assert len(days) == RIDES_LOOKAHEAD_DAYS + 1
    assert days[0] == _TODAY
    assert days[-1] == date(2026, 9, 6)


def test_overlapping_dates_only_inside_window() -> None:
    window = _window()
    assert window.overlapping_dates(date(2026, 9, 5), date(2026, 9, 8)) == {
        "2026-09-05",
        "2026-09-06",
    }
    assert window.overlapping_dates(date(2026, 8, 1), date(2026, 8, 10)) == set()
    assert window.overlapping_dates(None, date(2026, 9, 3)) == set()


def test_needs_today_only_while_unfinished() -> None:
    window = _window()
    assert window.needs_today() is True
    window.set_day("2026-09-02", [_entry(10, "New", "2026-09-02T06:00:00Z")])
    assert window.needs_today() is True
    window.set_day("2026-09-02", [_entry(10, "Finished", "2026-09-02T06:00:00Z")])
    assert window.needs_today() is False
    assert window.needs_today({"2026-09-02"}) is True


def test_next_missing_date_skips_loaded() -> None:
    window = _window()
    window.set_day("2026-09-02", [])
    assert window.next_missing_date() == date(2026, 9, 3)
    window.set_day("2026-09-03", [])
    assert window.next_missing_date() == date(2026, 9, 4)
    for day in ("2026-09-04", "2026-09-05", "2026-09-06"):
        window.set_day(day, [])
    assert window.next_missing_date() is None


def test_start_day_drops_past_dates() -> None:
    window = _window(date(2026, 9, 1))
    window.set_day("2026-09-01", [_entry(9, "Finished", "2026-09-01T06:00:00Z")])
    window.set_day("2026-09-02", [_entry(10, "New", "2026-09-02T06:00:00Z")])
    window.start_day(_TODAY)
    assert [occ["ride_id"] for occ in window.occurrences] == [10]
    assert window.loaded_dates == {"2026-09-02"}


def test_bind_unfinished_today_wins() -> None:
    window = _window()
    window.set_day("2026-09-02", [_entry(10, "New", "2026-09-02T06:00:00Z")])
    window.set_day("2026-09-03", [_entry(11, "New", "2026-09-03T06:00:00Z")])
    bound = window.bind()["1:120"]
    assert bound["ride_id"] == 10
    assert bound["assigned_today"] is True


def test_bind_keeps_finished_today() -> None:
    window = _window()
    window.set_day("2026-09-02", [_entry(10, "Finished", "2026-09-02T06:00:00Z")])
    window.set_day("2026-09-03", [_entry(11, "New", "2026-09-03T06:00:00Z")])
    bound = window.bind()["1:120"]
    assert bound["ride_id"] == 10
    assert bound["status"] == "Finished"
    assert window.map_focus_key is None


def test_bind_skips_line_without_today() -> None:
    window = _window()
    window.set_day("2026-09-03", [_entry(11, "New", "2026-09-03T06:00:00Z")])
    assert window.bind() == {}


def test_bind_keeps_position_for_same_ride() -> None:
    window = _window()
    window.set_day("2026-09-02", [_entry(10, "Ongoing", "2026-09-02T06:00:00Z")])
    window.bind()
    window.rides["1:120"]["lat"] = 32.1
    window.rides["1:120"]["lng"] = 34.8
    window.set_day("2026-09-02", [_entry(10, "Ongoing", "2026-09-02T06:00:00Z")])
    bound = window.bind()["1:120"]
    assert (bound["lat"], bound["lng"]) == (32.1, 34.8)
    assert window.live_key == "1:120"


def test_focus_moves_to_next_day_when_today_finished() -> None:
    window = _window()
    window.set_day("2026-09-02", [_entry(10, "Finished", "2026-09-02T06:00:00Z")])
    window.set_day(
        "2026-09-03", [_entry(20, "New", "2026-09-03T06:00:00Z", route_id=2)]
    )
    focus = window.focus
    assert focus is not None
    assert focus["ride_id"] == 20


def test_focus_prefers_live_over_earlier_start() -> None:
    window = _window()
    window.set_day(
        "2026-09-02",
        [
            _entry(10, "New", "2026-09-02T13:00:00Z"),
            _entry(11, "OngoingMonitored", "2026-09-02T14:00:00Z", route_id=2),
        ],
    )
    focus = window.focus
    assert focus is not None
    assert focus["ride_id"] == 11


def test_apply_status_patches_occurrence_and_bound() -> None:
    window = _window()
    window.set_day("2026-09-02", [_entry(10, "New", "2026-09-02T06:00:00Z")])
    window.bind()
    applied = window.apply_status(10, "OngoingMonitored")
    assert applied == ("1:120", "New")
    assert window.rides["1:120"]["status"] == "OngoingMonitored"
    assert window.occurrence_for(10)["status"] == "OngoingMonitored"
    assert window.live_key == "1:120"


def test_apply_status_unknown_ride() -> None:
    window = _window()
    window.set_day("2026-09-02", [_entry(10, "New", "2026-09-02T06:00:00Z")])
    assert window.apply_status(999, "Finished") is None
