"""Listed ride calendar events (HA-free, no I/O)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .rides import Ride
from .stations import Station

_ISRAEL = ZoneInfo("Asia/Jerusalem")

_KIND_ONBOARDING = "onboarding"
_KIND_ON_THE_WAY = "on_the_way"
_KIND_ETA = "eta"

_KIND_LABEL = {
    _KIND_ONBOARDING: "Onboarding",
    _KIND_ON_THE_WAY: "On-the-way",
    _KIND_ETA: "ETA",
}


@dataclass(frozen=True)
class RideCalendarItem:
    """One calendar leg on one service date."""

    uid: str
    summary: str
    start: datetime
    end: datetime
    location: str
    description: str
    service_date: str
    key: str
    kind: str


def events_for_line(
    occurrences: Iterable[Any],
    ride_key: str,
    start: datetime,
    end: datetime,
    member_id: int | None = None,
) -> list[RideCalendarItem]:
    """Listed occurrence legs for ``ride_key`` that overlap ``[start, end)``."""
    out: list[RideCalendarItem] = []
    for occ in _line_occurrences(occurrences, ride_key):
        for item in items_from_occurrence(occ, member_id):
            if _overlaps(item, start, end):
                out.append(item)
    return out


def current_event(
    occurrences: Iterable[Any],
    ride_key: str,
    today: date,
    now: datetime | None = None,
    member_id: int | None = None,
) -> RideCalendarItem | None:
    """Next unfinished today leg, else the first leg of the next listed day."""
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
        items = items_from_occurrence(today_occ, member_id)
        if items:
            upcoming = [item for item in items if item.end > moment]
            if upcoming:
                return upcoming[0]
            ride = Ride.from_cache(today_occ)
            if not ride.is_finished:
                return items[-1]
    for occ in later:
        items = items_from_occurrence(occ, member_id)
        if items:
            return items[0]
    return None


def items_from_occurrence(
    occ: Mapping[str, Any], member_id: int | None = None
) -> list[RideCalendarItem]:
    """Onboarding, On-the-way, and ETA legs with a positive duration."""
    ride = Ride.from_cache(occ)
    start = ride.start
    if start is None:
        return []
    service_date = str(occ.get("service_date") or start.date().isoformat())
    key = str(occ.get("key") or ride.key or "")
    title = ride.device_name(member_id) or ride.name or key
    description = _description(ride)
    boarding = ride.boarding_station()
    dropoff = ride.dropoff_station(member_id)
    board_addr = _address(boarding, ride.passenger_stop)
    dest_addr = _address(dropoff, ride.passenger_destination)
    legs: list[tuple[str, datetime | None, datetime | None, str]] = [
        (_KIND_ONBOARDING, ride.start, ride.boarding_at, board_addr),
        (_KIND_ON_THE_WAY, ride.boarding_at, ride.dropoff_at, dest_addr),
        (_KIND_ETA, ride.dropoff_at, ride.end, dest_addr),
    ]
    out: list[RideCalendarItem] = []
    for kind, begin, finish, location in legs:
        if begin is None or finish is None or finish <= begin:
            continue
        label = _KIND_LABEL[kind]
        out.append(
            RideCalendarItem(
                uid=f"{key}:{service_date}:{kind}",
                summary=f"{title} · {label}",
                start=begin,
                end=finish,
                location=location,
                description=description,
                service_date=service_date,
                key=key,
                kind=kind,
            )
        )
    return out


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


def _address(station: Station | None, fallback: str) -> str:
    if station is not None:
        return station.address or station.name or fallback
    return fallback


def _fmt(moment: datetime | None) -> str:
    if moment is None:
        return "—"
    return moment.astimezone(_ISRAEL).strftime("%H:%M")


def _description(ride: Ride) -> str:
    lines = [f"Status: {ride.status or 'scheduled'}"]
    board = ride.passenger_stop
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
