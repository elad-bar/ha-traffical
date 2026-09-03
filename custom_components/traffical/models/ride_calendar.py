"""Listed ride calendar events (HA-free, no I/O)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .rides import Ride


@dataclass(frozen=True)
class RideCalendarItem:
    """One calendar event: a line on one service date."""

    uid: str
    summary: str
    start: datetime
    end: datetime
    location: str
    description: str
    service_date: str
    key: str


def events_for_line(
    occurrences: Iterable[Any],
    ride_key: str,
    start: datetime,
    end: datetime,
) -> list[RideCalendarItem]:
    """Listed occurrences for ``ride_key`` that overlap ``[start, end)``."""
    out: list[RideCalendarItem] = []
    for occ in _line_occurrences(occurrences, ride_key):
        item = item_from_occurrence(occ)
        if item is not None and _overlaps(item, start, end):
            out.append(item)
    return out


def current_event(
    occurrences: Iterable[Any],
    ride_key: str,
    today: date,
    now: datetime | None = None,
) -> RideCalendarItem | None:
    """Today's event while it is unfinished or still running, else the next listed day."""
    moment = now or datetime.now(timezone.utc)
    today_iso = today.isoformat()
    today_occ: dict[str, Any] | None = None
    later: list[dict[str, Any]] = []
    for occ in _line_occurrences(occurrences, ride_key):
        service_date = str(occ.get("service_date") or "")
        if service_date == today_iso:
            today_occ = occ
        elif service_date > today_iso:
            later.append(occ)
    if today_occ is not None:
        item = item_from_occurrence(today_occ)
        if item is not None:
            ride = Ride.from_cache(today_occ)
            if not ride.is_finished or item.end > moment:
                return item
    for occ in later:
        item = item_from_occurrence(occ)
        if item is not None:
            return item
    return None


def item_from_occurrence(occ: Mapping[str, Any]) -> RideCalendarItem | None:
    """Build an event from a listed occurrence, including station actuals."""
    ride = Ride.from_cache(occ)
    start = ride.start
    end = ride.end
    if start is None:
        return None
    if end is None:
        end = start + timedelta(minutes=45)
    service_date = str(occ.get("service_date") or start.date().isoformat())
    key = str(occ.get("key") or ride.key or "")
    return RideCalendarItem(
        uid=f"{key}:{service_date}",
        summary=ride.name or key,
        start=start,
        end=end,
        location=_location(ride),
        description=_description(ride),
        service_date=service_date,
        key=key,
    )


def _line_occurrences(
    occurrences: Iterable[Any], ride_key: str
) -> list[dict[str, Any]]:
    wanted = str(ride_key or "")
    out: list[dict[str, Any]] = []
    for raw in occurrences:
        if not isinstance(raw, Mapping):
            continue
        occ = dict(raw)
        key = str(occ.get("key") or Ride.from_cache(occ).key or "")
        if not key or key != wanted:
            continue
        occ["key"] = key
        out.append(occ)
    out.sort(key=lambda occ: str(occ.get("service_date") or ""))
    return out


def _overlaps(item: RideCalendarItem, start: datetime, end: datetime) -> bool:
    return item.start < end and item.end > start


def _location(ride: Ride) -> str:
    boarding = ride.boarding_station()
    if boarding is not None:
        return boarding.label
    return ride.passenger_stop


def _fmt(moment: datetime | None) -> str:
    if moment is None:
        return "—"
    return moment.astimezone(timezone.utc).strftime("%H:%M")


def _description(ride: Ride) -> str:
    lines = [f"Status: {ride.status or 'scheduled'}"]
    board = ride.passenger_stop or _location(ride)
    dest = ride.passenger_destination
    lines.append(f"Boarding: {board} {_fmt(ride.boarding_at)}")
    if dest:
        lines.append(f"Drop-off: {dest} {_fmt(ride.dropoff_at)}")
    stations = ride.stations
    if not stations:
        return "\n".join(lines)
    lines.append("Stops:")
    for station in stations:
        planned = _fmt(station.arrival_time)
        if station.actual_arrival is not None:
            stamp = f"{planned} actual {_fmt(station.actual_arrival)}"
        else:
            stamp = planned
        lines.append(f"- {station.label}: {stamp}")
    return "\n".join(lines)
