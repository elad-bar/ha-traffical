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
from .models.rides import Ride
from .models.stations import Station

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
            for station in Ride.from_cache(ride).stations:
                sid = station.station_id
                if sid:
                    out.append((key, sid, station.raw))
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

    def _station(self) -> Station:
        ride = self.coordinator.ride(self.ride_key or "")
        for station in Ride.from_cache(ride).stations:
            if station.station_id == self._stop_id:
                return station
        return Station({})

    @property
    def name(self) -> str | None:
        return self._station().label or self._stop_id

    @property
    def latitude(self) -> float | None:
        return self._station().lat

    @property
    def longitude(self) -> float | None:
        return self._station().lng

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ride = self.coordinator.ride(self.ride_key or "")
        station = self._station()
        home = station.is_yours(
            Ride.from_cache(ride).passenger_stop, self.coordinator.member_id()
        )
        passed = station.arrived or self._stop_id in set(
            ride.get("passed_stations") or []
        )
        kind = "pending"
        if home:
            kind = "home"
        elif station.is_target:
            kind = "target"
        elif passed:
            kind = "passed"
        return {
            "station_id": self._stop_id,
            "name": station.name,
            "address": station.address,
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
