"""Station geo_location markers."""

from __future__ import annotations

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.consts import DOMAIN
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
        hass, entry, coordinator, "geo_location", async_add_entities, TrafficalStop
    )


class TrafficalStop(TrafficalEntity, GeolocationEvent):
    _attr_source = DOMAIN

    @property
    def name(self) -> str | None:
        return self._resolver.resolve_name(self.spec, self._state(), self._entity_ctx)

    @property
    def icon(self) -> str | None:
        return self._resolver.resolve_icon(self.spec, self._state(), self._entity_ctx)

    @property
    def latitude(self) -> float | None:
        return self._position(0)

    @property
    def longitude(self) -> float | None:
        return self._position(1)

    def _position(self, index: int) -> float | None:
        position = self._state_value()
        return position[index] if position else None
