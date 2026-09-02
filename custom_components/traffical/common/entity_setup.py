"""Add hub + per-ride entities as rides appear."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..managers.coordinator import TrafficalCoordinator
from .base_entity import TrafficalEntity

EntityFactory = Callable[..., TrafficalEntity]


def async_setup_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: TrafficalCoordinator,
    async_add_entities: AddEntitiesCallback,
    hub_keys: tuple[str, ...],
    ride_keys: tuple[str, ...],
    entity_factory: EntityFactory,
) -> None:
    known: dict[tuple[str | None, str], TrafficalEntity] = {}

    def _add(ride_key: str | None, keys: tuple[str, ...]) -> None:
        to_add: list[TrafficalEntity] = []
        for key in keys:
            ident = (ride_key, key)
            if ident in known:
                continue
            entity = entity_factory(coordinator, key, ride_key)
            known[ident] = entity
            to_add.append(entity)
        if to_add:
            async_add_entities(to_add)

    _add(None, hub_keys)
    for ride_key in coordinator.ride_keys:
        _add(ride_key, ride_keys)

    @callback
    def _on_update() -> None:
        for ride_key in coordinator.ride_keys:
            _add(ride_key, ride_keys)

    unsub = coordinator.async_add_listener(_on_update)
    entry.async_on_unload(unsub)
