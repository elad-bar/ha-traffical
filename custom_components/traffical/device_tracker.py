"""Traffical bus device tracker."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.entity_setup import async_setup_entities
from .managers.coordinator import TrafficalCoordinator

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
        "device_tracker",
        async_add_entities,
        TrafficalBusTracker,
    )


class TrafficalBusTracker(TrafficalEntity, TrackerEntity):
    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self._position(0)

    @property
    def longitude(self) -> float | None:
        return self._position(1)

    def _position(self, index: int) -> float | None:
        if not self.available:
            return None
        position = self._state_value()
        return position[index] if position else None
