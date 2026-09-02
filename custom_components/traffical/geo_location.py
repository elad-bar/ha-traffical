"""Station geo_location markers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.consts import DOMAIN
from .managers.coordinator import TrafficalCoordinator
from .models.rides import is_your_station, station_id

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TrafficalCoordinator = entry.runtime_data
    known: dict[tuple[str, str], TrafficalStop] = {}

    def _wanted() -> list[tuple[str, str, dict[str, Any]]]:
        out: list[tuple[str, str, dict[str, Any]]] = []
        for key, ride in (coordinator.data.get("rides") or {}).items():
            if not ride.get("assigned_today"):
                continue
            details = ride.get("details") or {}
            for station in details.get("stations") or []:
                if not isinstance(station, dict):
                    continue
                sid = station_id(station)
                if sid:
                    out.append((key, sid, station))
        return out

    def _sync() -> None:
        to_add: list[TrafficalStop] = []
        wanted = {(k, s): st for k, s, st in _wanted()}
        for ident, station in wanted.items():
            if ident in known:
                continue
            entity = TrafficalStop(coordinator, ident[0], ident[1], station)
            known[ident] = entity
            to_add.append(entity)
        if to_add:
            async_add_entities(to_add)

    _sync()

    @callback
    def _on_update() -> None:
        _sync()

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class TrafficalStop(TrafficalEntity, GeolocationEvent):
    def __init__(
        self,
        coordinator: TrafficalCoordinator,
        ride_key: str,
        stop_id: str,
        station: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, f"stop_{stop_id}", ride_key)
        self._stop_id = stop_id
        self._attr_source = DOMAIN

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        ride = self.coordinator.ride(self.ride_key or "")
        focus = (self.coordinator.data or {}).get("focus_ride_key")
        return bool(ride.get("assigned_today")) and self.ride_key == focus

    def _station(self) -> dict[str, Any]:
        ride = self.coordinator.ride(self.ride_key or "")
        details = ride.get("details") or {}
        for station in details.get("stations") or []:
            if isinstance(station, dict) and station_id(station) == self._stop_id:
                return station
        return {}

    @property
    def name(self) -> str | None:
        station = self._station()
        if station.get("isTarget"):
            return str(station.get("name") or station.get("address") or self._stop_id)
        return str(station.get("address") or station.get("name") or self._stop_id)

    @property
    def latitude(self) -> float | None:
        try:
            return float(self._station().get("lat"))
        except (TypeError, ValueError):
            return None

    @property
    def longitude(self) -> float | None:
        try:
            return float(self._station().get("lng"))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._station()
        ride = self.coordinator.ride(self.ride_key or "")
        info = (ride.get("list_row") or {}).get("rideInfo") or {}
        member_id = self.coordinator.member_id()
        home = is_your_station(
            station, str(info.get("passengerStationName") or ""), member_id
        )
        passed = self._stop_id in set(ride.get("passed_stations") or [])
        if station.get("actualArriveDateTime"):
            passed = True
        kind = "pending"
        if home:
            kind = "home"
        elif station.get("isTarget"):
            kind = "target"
        elif passed:
            kind = "passed"
        return {
            "station_id": self._stop_id,
            "name": station.get("name"),
            "address": station.get("address"),
            "kind": kind,
            "passed": passed,
        }

    @property
    def icon(self) -> str:
        attrs = self.extra_state_attributes
        kind = attrs.get("kind")
        if kind == "home":
            return "mdi:home"
        if kind == "target":
            return "mdi:school"
        if attrs.get("passed"):
            return "mdi:bus-stop-uncovered"
        return "mdi:bus-stop"
