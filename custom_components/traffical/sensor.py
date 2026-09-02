"""Traffical sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.entity_descriptions import HUB_SENSORS, RIDE_SENSORS
from .common.entity_setup import async_setup_entities
from .managers.coordinator import TrafficalCoordinator
from .models.rides import Ride

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TrafficalCoordinator = entry.runtime_data
    async_setup_entities(
        hass,
        entry,
        coordinator,
        async_add_entities,
        HUB_SENSORS,
        RIDE_SENSORS,
        TrafficalSensor,
    )


class TrafficalSensor(TrafficalEntity, SensorEntity):
    @property
    def native_value(self) -> Any:
        if self.ride_key is None:
            return self._next_ride()
        ride = self.coordinator.ride(self.ride_key)
        details = ride.get("details") or {}
        info = (ride.get("list_row") or {}).get("rideInfo") or {}
        if self.entity_key == "status":
            return ride.get("status")
        if self.entity_key == "my_station":
            return self._my_station_label(ride)
        if self.entity_key == "destination":
            return self._destination_label(details)
        if self.entity_key == "driver":
            driver = details.get("driver")
            if isinstance(driver, dict):
                return driver.get("name") or None
            return info.get("driver") or None
        if self.entity_key == "vehicle":
            return details.get("carNumber") or info.get("carNumber")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.ride_key is None:
            ride = self._next_ride_obj()
            if not ride:
                return {}
            info = (ride.get("list_row") or {}).get("rideInfo") or {}
            return {
                "ride_id": ride.get("ride_id"),
                "ticket": ride.get("ticket"),
                "direction": ride.get("direction"),
                "status": ride.get("status"),
                "service_date": ride.get("service_date"),
            }
        ride = self.coordinator.ride(self.ride_key)
        details = ride.get("details") or {}
        info = (ride.get("list_row") or {}).get("rideInfo") or {}
        if self.entity_key == "my_station":
            return {"name": info.get("passengerStationName")}
        if self.entity_key == "destination":
            return {"address": self._destination_address(details)}
        if self.entity_key == "vehicle":
            return {
                "type": details.get("carTypeId"),
                "shuttle_company": details.get("shuttleCompanyName")
                or info.get("shuttleCompany"),
            }
        if self.entity_key == "status":
            return {"ride_id": ride.get("ride_id"), "ticket": ride.get("ticket")}
        return {}

    def _next_ride_obj(self) -> dict[str, Any] | None:
        focus = (self.coordinator.data or {}).get("focus")
        return focus if isinstance(focus, dict) else None

    def _next_ride(self) -> str | None:
        ride = self._next_ride_obj()
        if ride is None:
            return None
        return ride.get("name")

    def _my_station_label(self, ride) -> str | None:
        cached = Ride.from_cache(ride)
        station = cached.your_station(self.coordinator.member_id())
        stop = cached.passenger_stop
        if station is None:
            return stop or None
        return station.address or station.name or stop

    def _destination_label(self, details) -> str | None:
        station = Ride({}, details).target_station()
        if station is None:
            return None
        return station.name or station.address

    def _destination_address(self, details) -> str | None:
        station = Ride({}, details).target_station()
        return station.address if station is not None else None
