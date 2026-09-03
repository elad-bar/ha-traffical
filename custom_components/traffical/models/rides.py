"""Ride shape (HA-free, no I/O)."""

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
from .stations import Station


def rides_customer_type(customer_type_id: Any) -> str:
    try:
        type_id = int(customer_type_id)
    except (TypeError, ValueError):
        return DEFAULT_RIDES_CUSTOMER_TYPE
    return CUSTOMER_TYPE_PATHS.get(type_id) or DEFAULT_RIDES_CUSTOMER_TYPE


def ride_device_key(route_id: Any, direction: Any) -> str | None:
    """Stable device id for a recurring line, not the daily ``rideId``."""
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


class Ride:
    """One day's ride, built from a list row and optional details."""

    def __init__(self, list_row: Any, details: Any = None) -> None:
        self._row = list_row if isinstance(list_row, dict) else {}
        self._details = details if isinstance(details, dict) else {}
        info = self._row.get("rideInfo")
        self._info = info if isinstance(info, dict) else {}

    @classmethod
    def from_cache(cls, record: Any) -> Ride:
        """Rebuild from a coordinator / CLI cache entry."""
        record = record if isinstance(record, dict) else {}
        return cls(record.get("list_row"), record.get("details"))

    @property
    def ticket(self) -> str:
        return str(self._info.get("rideTicket") or self._row.get("rideTicket") or "")

    @property
    def ride_id(self) -> int | None:
        raw = self._info.get("rideId") or self._row.get("rideId")
        if raw is None:
            raw = self._details.get("rideId")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def route_id(self) -> Any:
        return (
            self._details.get("routeId")
            or self._info.get("routeId")
            or self._row.get("routeId")
        )

    @property
    def direction(self) -> Any:
        return (
            self._details.get("direction")
            or self._info.get("direction")
            or self._row.get("direction")
        )

    @property
    def key(self) -> str | None:
        return ride_device_key(self.route_id, self.direction)

    @property
    def name(self) -> str:
        return str(
            self._details.get("name")
            or self._row.get("name")
            or self._row.get("number")
            or ""
        )

    @property
    def status(self) -> str:
        return str(self._details.get("status") or self._row.get("status") or "")

    @property
    def is_live(self) -> bool:
        return status_live(self.status)

    @property
    def is_finished(self) -> bool:
        return status_finished(self.status)

    @property
    def start(self) -> datetime | None:
        return parse_utc(
            self._details.get("startTime") or self._info.get("startDateTime")
        )

    @property
    def end(self) -> datetime | None:
        return parse_utc(self._details.get("endTime") or self._info.get("endDateTime"))

    @property
    def passenger_stop(self) -> str:
        return str(self._info.get("passengerStationName") or "")

    @property
    def passenger_destination(self) -> str:
        return str(self._info.get("passengerDestinationName") or "")

    @property
    def boarding_at(self) -> datetime | None:
        return parse_utc(self._info.get("passengerStationArrivalDateTime"))

    @property
    def dropoff_at(self) -> datetime | None:
        return parse_utc(self._info.get("passengerDestinationArrivalDateTime"))

    @property
    def stations(self) -> list[Station]:
        raw = self._details.get("stations")
        if not isinstance(raw, list):
            return []
        return [Station(item) for item in raw if isinstance(item, dict)]

    def your_station(self, member_id: int | None) -> Station | None:
        stop = self.passenger_stop
        for station in self.stations:
            if station.is_yours(stop, member_id):
                return station
        return None

    def boarding_station(self) -> Station | None:
        """Boarding stop by ``passengerStationName`` only (not ``passengers[]``)."""
        stop = self.passenger_stop.strip()
        if not stop:
            return None
        for station in self.stations:
            if station.name == stop:
                return station
        return None

    def dropoff_station(self, _member_id: int | None = None) -> Station | None:
        """Passenger drop-off by destination name, not the school ``isTarget`` stop."""
        dest = self.passenger_destination.strip()
        if not dest:
            return None
        for station in self.stations:
            if station.name == dest:
                return station
        return None

    def home_station(self, member_id: int | None) -> Station | None:
        """The house stop: assigned passenger row, else drop-off when boarding is school."""
        assigned = [
            station for station in self.stations if station.has_passenger(member_id)
        ]
        if assigned:
            return assigned[0]
        boarding = self.boarding_station()
        if boarding is not None and boarding.is_target:
            return self.dropoff_station()
        return boarding

    def device_name(self, member_id: int | None = None) -> str:
        """Friendly HA device title from from/to addresses, or empty."""
        pickup = self.your_station(member_id)
        dropoff = self.dropoff_station(member_id)
        from_addr = pickup.address if pickup is not None else ""
        to_addr = dropoff.address if dropoff is not None else ""
        if not from_addr or not to_addr:
            return ""
        return f"Traffical {from_addr} - {to_addr}"

    def target_station(self) -> Station | None:
        for station in self.stations:
            if station.is_target:
                return station
        return None

    def occurrence(
        self, service_date: str, checkin: Any = None
    ) -> dict[str, Any] | None:
        """Cache record for this ride on one service date."""
        key = self.key
        if key is None:
            return None
        return {
            "key": key,
            "service_date": service_date,
            "route_id": self.route_id,
            "direction": self.direction,
            "ride_id": self.ride_id,
            "ticket": self.ticket,
            "name": self.name,
            "status": self.status,
            "list_row": self._row,
            "details": self._details,
            "checkin": checkin,
            "assigned_today": False,
            "lat": None,
            "lng": None,
            "passed_stations": set(),
            "approaching_fired": False,
        }


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
        return Ride.from_cache(item[1]).start or far

    upcoming.sort(key=_sort_start)
    return upcoming[0][0]
