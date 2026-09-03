"""Resolve EntitySpec values, attributes and availability (HA-free).

Platforms never read the coordinator payload directly: they hand a spec and the
state for its scope to :class:`EntityValueResolver`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

from .coordinates import haversine_m
from .entity_specs import SCOPE_HUB, SCOPE_STATION, EntitySpec, policy_active
from .rides import Ride, status_finished, status_live
from .stations import Station

Resolver = Callable[[Mapping[str, Any], "EntityContext"], Any]


@dataclass(frozen=True)
class EntityContext:
    """Account-level state shared by every entity of one config entry."""

    member_id: int | None = None
    session_ok: bool = False
    children: tuple[Mapping[str, Any], ...] = ()
    policies: Mapping[str, Any] = field(default_factory=dict)
    focus: Mapping[str, Any] | None = None
    focus_ride_key: str | None = None
    passenger_name: str = ""

    def policy_active(self, group: str) -> bool:
        return policy_active(self.policies, group)


def get_path(data: Any, path: str) -> Any:
    """Read a dotted path out of nested mappings / sequences."""
    current = data
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, (list, tuple)):
            try:
                index = int(part)
            except ValueError:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def ride_record(spec: EntitySpec, state: Mapping[str, Any]) -> Mapping[str, Any]:
    """The ride dict for a spec's scope (station state nests it under ``ride``)."""
    if spec.scope == SCOPE_STATION:
        nested = state.get("ride")
        return nested if isinstance(nested, Mapping) else {}
    return state


def child_label(child: Mapping[str, Any]) -> str:
    name = " ".join(
        part for part in (child.get("firstName"), child.get("lastName")) if part
    )
    return name or str(child.get("memberId"))


def child_id_for_label(label: str, ctx: EntityContext) -> str | None:
    """Reverse a select option back to the member id it represents."""
    for child in ctx.children:
        if child_label(child) == label:
            return str(child.get("memberId"))
    return None


def _checkin(ride: Mapping[str, Any]) -> Mapping[str, Any]:
    check = ride.get("checkin")
    return check if isinstance(check, Mapping) else {}


def _ride_info(ride: Mapping[str, Any]) -> Mapping[str, Any]:
    info = (ride.get("list_row") or {}).get("rideInfo")
    return info if isinstance(info, Mapping) else {}


def _station(state: Mapping[str, Any]) -> Station:
    ride = state.get("ride") if isinstance(state.get("ride"), Mapping) else {}
    station_id = state.get("station_id")
    for station in Ride.from_cache(ride).stations:
        if station.station_id == station_id:
            return station
    return Station({})


def _status(ride: Mapping[str, Any]) -> str:
    return str(ride.get("status") or "")


def _is_checked_in(ride: Mapping[str, Any]) -> bool:
    return bool(_checkin(ride).get("checkIn"))


class EntityValueResolver:
    """Map an EntitySpec to its state, attributes, options and availability."""

    def __init__(self) -> None:
        self._values: dict[str, Resolver] = {
            "next_ride": self._next_ride,
            "my_station": self._my_station,
            "destination": self._destination,
            "driver": self._driver,
            "vehicle": self._vehicle,
            "checked_in": self._checked_in,
            "bus_position": self._bus_position,
            "station_position": self._station_position,
            "child_current": self._child_current,
            "boarding_at": self._boarding_at,
            "dropoff_at": self._dropoff_at,
        }
        self._attributes: dict[str, Resolver] = {
            "next_ride": self._attrs_next_ride,
            "status": self._attrs_status,
            "my_station": self._attrs_my_station,
            "destination": self._attrs_destination,
            "vehicle": self._attrs_vehicle,
            "checked_in": self._attrs_checked_in,
            "station": self._attrs_station,
        }
        self._options: dict[str, Resolver] = {
            "child_options": self._child_options,
        }
        self._names: dict[str, Resolver] = {
            "station_label": self._station_label,
        }
        self._icons: dict[str, Resolver] = {
            "station_icon": self._station_icon,
        }
        self._availability: dict[str, Resolver] = {
            "multi_child": self._avail_multi_child,
            "can_check_in": self._avail_can_check_in,
            "can_check_out": self._avail_can_check_out,
            "can_not_come": self._avail_can_not_come,
            "gps_live": self._avail_gps_live,
            "focus_station": self._avail_focus_station,
        }

    def resolve_value(
        self, spec: EntitySpec, state: Mapping[str, Any], ctx: EntityContext
    ) -> Any:
        if spec.resolve:
            resolver = self._values.get(spec.resolve)
            return resolver(state, ctx) if resolver else None
        if spec.data_path:
            return get_path(state, spec.data_path)
        return None

    def resolve_attributes(
        self, spec: EntitySpec, state: Mapping[str, Any], ctx: EntityContext
    ) -> dict[str, Any]:
        if not spec.attributes:
            return {}
        resolver = self._attributes.get(spec.attributes)
        return dict(resolver(state, ctx) or {}) if resolver else {}

    def resolve_options(
        self, spec: EntitySpec, state: Mapping[str, Any], ctx: EntityContext
    ) -> list[str]:
        if spec.options:
            return list(spec.options)
        if not spec.options_resolve:
            return []
        resolver = self._options.get(spec.options_resolve)
        return list(resolver(state, ctx) or []) if resolver else []

    def resolve_name(
        self, spec: EntitySpec, state: Mapping[str, Any], ctx: EntityContext
    ) -> str | None:
        if not spec.dynamic_name:
            return None
        resolver = self._names.get(spec.dynamic_name)
        return resolver(state, ctx) if resolver else None

    def resolve_icon(
        self, spec: EntitySpec, state: Mapping[str, Any], ctx: EntityContext
    ) -> str | None:
        if not spec.icon_resolve:
            return spec.icon
        resolver = self._icons.get(spec.icon_resolve)
        return (resolver(state, ctx) if resolver else None) or spec.icon

    def is_available(
        self, spec: EntitySpec, state: Mapping[str, Any], ctx: EntityContext
    ) -> bool:
        if not ctx.session_ok:
            return False
        if spec.scope != SCOPE_HUB and not ride_record(spec, state).get(
            "assigned_today"
        ):
            return False
        if not spec.availability:
            return True
        rule = self._availability.get(spec.availability)
        return bool(rule(state, ctx)) if rule else True

    # --- values ---

    @staticmethod
    def _next_ride(_state: Mapping[str, Any], ctx: EntityContext) -> Any:
        return (ctx.focus or {}).get("name")

    @staticmethod
    def _my_station(state: Mapping[str, Any], ctx: EntityContext) -> Any:
        ride = Ride.from_cache(state)
        station = ride.boarding_station() or ride.your_station(ctx.member_id)
        stop = ride.passenger_stop
        if station is None:
            return stop or None
        return station.address or station.name or stop

    @staticmethod
    def _destination(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        ride = Ride.from_cache(state)
        station = ride.dropoff_station()
        if station is None:
            return ride.passenger_destination or None
        return station.label or ride.passenger_destination

    @staticmethod
    def _driver(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        details = state.get("details") or {}
        driver = details.get("driver")
        if isinstance(driver, Mapping):
            return driver.get("name") or None
        return _ride_info(state).get("driver") or None

    @staticmethod
    def _vehicle(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        details = state.get("details") or {}
        return details.get("carNumber") or _ride_info(state).get("carNumber")

    @staticmethod
    def _boarding_at(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        return Ride.from_cache(state).boarding_at

    @staticmethod
    def _dropoff_at(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        return Ride.from_cache(state).dropoff_at

    @staticmethod
    def _checked_in(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        check = _checkin(state)
        if check.get("checkIn") is None:
            return None
        return bool(check.get("checkIn"))

    @staticmethod
    def _bus_position(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        lat, lng = state.get("lat"), state.get("lng")
        if lat is None or lng is None:
            return None
        return (lat, lng)

    @staticmethod
    def _station_position(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        station = _station(state)
        if station.lat is None or station.lng is None:
            return None
        return (station.lat, station.lng)

    @staticmethod
    def _child_current(_state: Mapping[str, Any], ctx: EntityContext) -> Any:
        for child in ctx.children:
            if str(child.get("memberId")) == str(ctx.member_id):
                return child_label(child)
        labels = [child_label(child) for child in ctx.children]
        if labels:
            return labels[0]
        return ctx.passenger_name or "passenger"

    # --- options / name / icon ---

    @staticmethod
    def _child_options(_state: Mapping[str, Any], ctx: EntityContext) -> Any:
        labels = [child_label(child) for child in ctx.children]
        if labels:
            return labels
        return [ctx.passenger_name or "passenger"]

    @staticmethod
    def _station_label(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        return _station(state).label or state.get("station_id")

    @staticmethod
    def _station_icon(state: Mapping[str, Any], ctx: EntityContext) -> Any:
        kind = _station_kind(state, ctx)
        if kind == "home":
            return "mdi:home"
        if kind == "target":
            return "mdi:school"
        if kind == "passed":
            return "mdi:bus-stop-uncovered"
        return "mdi:bus-stop"

    # --- attributes ---

    @staticmethod
    def _attrs_next_ride(_state: Mapping[str, Any], ctx: EntityContext) -> Any:
        focus = ctx.focus
        if not focus:
            return {}
        return {
            "ride_id": focus.get("ride_id"),
            "ticket": focus.get("ticket"),
            "direction": focus.get("direction"),
            "status": focus.get("status"),
            "service_date": focus.get("service_date"),
        }

    @staticmethod
    def _attrs_status(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        return {"ride_id": state.get("ride_id"), "ticket": state.get("ticket")}

    @staticmethod
    def _attrs_my_station(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        arrival = Ride.from_cache(state).boarding_at
        return {
            "name": _ride_info(state).get("passengerStationName"),
            "arrival": arrival.isoformat() if arrival is not None else None,
        }

    @staticmethod
    def _attrs_destination(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        station = Ride.from_cache(state).dropoff_station()
        arrival = Ride.from_cache(state).dropoff_at
        return {
            "address": station.address if station is not None else None,
            "arrival": arrival.isoformat() if arrival is not None else None,
        }

    @staticmethod
    def _attrs_vehicle(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        details = state.get("details") or {}
        return {
            "type": details.get("carTypeId"),
            "shuttle_company": details.get("shuttleCompanyName")
            or _ride_info(state).get("shuttleCompany"),
        }

    @staticmethod
    def _attrs_checked_in(state: Mapping[str, Any], _ctx: EntityContext) -> Any:
        return {"check_in_at": _checkin(state).get("checkInAt")}

    @staticmethod
    def _attrs_station(state: Mapping[str, Any], ctx: EntityContext) -> Any:
        station = _station(state)
        kind = _station_kind(state, ctx)
        return {
            "station_id": state.get("station_id"),
            "name": station.name,
            "address": station.address,
            "kind": kind,
            "passed": _station_passed(state),
            "distance_m": _station_distance_m(state),
        }

    # --- availability ---

    @staticmethod
    def _avail_multi_child(_state: Mapping[str, Any], ctx: EntityContext) -> bool:
        return len(ctx.children) > 1

    @staticmethod
    def _avail_can_check_in(state: Mapping[str, Any], _ctx: EntityContext) -> bool:
        status = _status(state)
        if status_finished(status) or _is_checked_in(state):
            return False
        return status_live(status) or status.casefold() == "new"

    @staticmethod
    def _avail_can_check_out(state: Mapping[str, Any], _ctx: EntityContext) -> bool:
        return _is_checked_in(state) and not status_finished(_status(state))

    @staticmethod
    def _avail_can_not_come(state: Mapping[str, Any], _ctx: EntityContext) -> bool:
        return _status(state).casefold() == "new"

    @staticmethod
    def _avail_gps_live(state: Mapping[str, Any], _ctx: EntityContext) -> bool:
        return status_live(_status(state)) and state.get("lat") is not None

    @staticmethod
    def _avail_focus_station(state: Mapping[str, Any], ctx: EntityContext) -> bool:
        return state.get("ride_key") == ctx.focus_ride_key


def _same_station(left: Station, right: Station) -> bool:
    if left.station_id and right.station_id:
        return left.station_id == right.station_id
    return bool(left.name) and left.name == right.name


def _station_distance_m(state: Mapping[str, Any]) -> int | None:
    ride = state.get("ride") if isinstance(state.get("ride"), Mapping) else {}
    station = _station(state)
    lat, lng = ride.get("lat"), ride.get("lng")
    if lat is None or lng is None or station.lat is None or station.lng is None:
        return None
    return int(haversine_m(float(lat), float(lng), station.lat, station.lng))


def _station_passed(state: Mapping[str, Any]) -> bool:
    ride = state.get("ride") if isinstance(state.get("ride"), Mapping) else {}
    station = _station(state)
    passed = set(ride.get("passed_stations") or [])
    return station.arrived or state.get("station_id") in passed


def _station_kind(state: Mapping[str, Any], ctx: EntityContext) -> str:
    ride = state.get("ride") if isinstance(state.get("ride"), Mapping) else {}
    station = _station(state)
    home = Ride.from_cache(ride).home_station(ctx.member_id)
    if home is not None and _same_station(home, station):
        return "home"
    if station.is_target:
        return "target"
    if _station_passed(state):
        return "passed"
    return "pending"
