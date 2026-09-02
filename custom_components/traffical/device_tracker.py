"""Traffical bus device tracker."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.entity_setup import async_setup_entities
from .managers.coordinator import TrafficalCoordinator
from .models.rides import status_live

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
        (),
        ("bus",),
        TrafficalBusTracker,
    )


class TrafficalBusTracker(TrafficalEntity, TrackerEntity):
    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        if not self.available:
            return None
        return self.coordinator.ride(self.ride_key or "").get("lat")

    @property
    def longitude(self) -> float | None:
        if not self.available:
            return None
        return self.coordinator.ride(self.ride_key or "").get("lng")

    @property
    def available(self) -> bool:
        if not super().available or not self.ride_key:
            return False
        ride = self.coordinator.ride(self.ride_key)
        return status_live(str(ride.get("status") or "")) and ride.get("lat") is not None
