"""Ride / station shapes (HA-free, no I/O)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..common.consts import (
    CUSTOMER_TYPE_PATHS,
    DEFAULT_RIDES_CUSTOMER_TYPE,
    STATUS_FINISHED,
    STATUS_LIVE,
)
from ..common.helpers import parse_utc


def rides_customer_type(customer_type_id: Any) -> str:
    try:
        type_id = int(customer_type_id)
    except (TypeError, ValueError):
        return DEFAULT_RIDES_CUSTOMER_TYPE
    return CUSTOMER_TYPE_PATHS.get(type_id) or DEFAULT_RIDES_CUSTOMER_TYPE


def ride_device_key(route_id: Any, direction: Any) -> str | None:
    try:
        rid = int(route_id)
        direction_i = int(direction)
    except (TypeError, ValueError):
        return None
    return f"{rid}:{direction_i}"


def status_live(status: str) -> bool:
    return str(status or "").casefold() in STATUS_LIVE


def status_finished(status: str) -> bool:
    return str(status or "").casefold() in STATUS_FINISHED


def _ride_start(ride: dict[str, Any]) -> datetime | None:
    details = ride.get("details") if isinstance(ride.get("details"), dict) else {}
    row = ride.get("list_row") if isinstance(ride.get("list_row"), dict) else {}
    info = row.get("rideInfo") if isinstance(row.get("rideInfo"), dict) else {}
    return parse_utc(details.get("startTime") or info.get("startDateTime"))


def focus_ride_key(rides: dict[str, Any]) -> str | None:
    """Live ride, else earliest unfinished assigned ride today."""
    assigned: list[tuple[str, dict[str, Any]]] = []
    for key, ride in rides.items():
        if isinstance(ride, dict) and ride.get("assigned_today"):
            assigned.append((key, ride))
    for key, ride in assigned:
        if status_live(str(ride.get("status") or "")):
            return key
    upcoming = [
        (key, ride)
        for key, ride in assigned
        if not status_finished(str(ride.get("status") or ""))
    ]
    if not upcoming:
        return None
    far = datetime(9999, 12, 31, tzinfo=timezone.utc)

    def _sort_start(item: tuple[str, dict[str, Any]]) -> datetime:
        return _ride_start(item[1]) or far

    upcoming.sort(key=_sort_start)
    return upcoming[0][0]


def list_row_ids(row: dict[str, Any]) -> tuple[str, int | None]:
    info = row.get("rideInfo") if isinstance(row.get("rideInfo"), dict) else {}
    ticket = str(info.get("rideTicket") or row.get("rideTicket") or "")
    ride_id_raw = info.get("rideId") or row.get("rideId")
    try:
        ride_id = int(ride_id_raw) if ride_id_raw is not None else None
    except (TypeError, ValueError):
        ride_id = None
    return ticket, ride_id


def list_row_route_key(
    row: dict[str, Any], details: dict[str, Any] | None
) -> str | None:
    info = row.get("rideInfo") if isinstance(row.get("rideInfo"), dict) else {}
    details = details if isinstance(details, dict) else {}
    route_id = details.get("routeId") or info.get("routeId") or row.get("routeId")
    direction = (
        details.get("direction") or info.get("direction") or row.get("direction")
    )
    return ride_device_key(route_id, direction)


def ride_name(row: dict[str, Any], details: dict[str, Any] | None) -> str:
    details = details if isinstance(details, dict) else {}
    return str(details.get("name") or row.get("name") or row.get("number") or "")


def is_your_station(
    station: dict[str, Any], passenger_stop: str, member_id: int | None
) -> bool:
    name = (station.get("name") or station.get("stationName") or "").strip()
    if passenger_stop and name == passenger_stop.strip():
        return True
    if member_id is None:
        return False
    passengers = station.get("passengers") or []
    if not isinstance(passengers, list):
        return False
    for passenger in passengers:
        if not isinstance(passenger, dict):
            continue
        try:
            if int(passenger.get("id")) == member_id:
                return True
        except (TypeError, ValueError):
            continue
    return False


def station_id(station: dict[str, Any]) -> str | None:
    raw = station.get("stationId") or station.get("id")
    if raw is None:
        return None
    return str(raw)


def coord_from_payload(payload: Any) -> tuple[float | None, float | None]:
    if not isinstance(payload, dict):
        return None, None
    lat = payload.get("latitude") or payload.get("lat") or payload.get("Latitude")
    lng = payload.get("longitude") or payload.get("lng") or payload.get("Longitude")
    try:
        lat_f = float(lat) if lat is not None else None
        lng_f = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        return None, None
    return lat_f, lng_f
