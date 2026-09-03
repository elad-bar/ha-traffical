"""Spec-driven platform setup: add, remove and reconcile entities."""

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..managers.coordinator import TrafficalCoordinator
from ..models.entity_specs import (
    SCOPE_HUB,
    SCOPE_RIDE,
    SCOPE_STATION,
    EntitySpec,
    get_entity_specs,
    station_pins_wanted,
)
from ..models.rides import Ride
from .base_entity import TrafficalEntity

_LOGGER = logging.getLogger(__name__)

EntityFactory = Callable[
    [TrafficalCoordinator, EntitySpec, str | None, str | None], TrafficalEntity
]

# ride key, entity key, station id
EntityId = tuple[str | None, str, str | None]


def async_setup_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: TrafficalCoordinator,
    platform: str,
    async_add_entities: AddEntitiesCallback,
    entity_factory: EntityFactory,
) -> Callable[[], None]:
    """Create entities for every spec × ride × station; return unsub for unload."""
    known: dict[EntityId, TrafficalEntity] = {}

    def _wanted() -> dict[EntityId, tuple[EntitySpec, str | None, str | None]]:
        caps = coordinator.entity_caps()
        out: dict[EntityId, tuple[EntitySpec, str | None, str | None]] = {}
        for spec in get_entity_specs(platform, scope=SCOPE_HUB, caps=caps):
            out[(None, spec.key, None)] = (spec, None, None)
        for ride_key, ride in (coordinator.data.get("rides") or {}).items():
            for spec in get_entity_specs(
                platform, scope=SCOPE_RIDE, state=ride, caps=caps
            ):
                out[(ride_key, spec.key, None)] = (spec, ride_key, None)
            if not station_pins_wanted(
                ride_key, ride, (coordinator.data or {}).get("focus_ride_key")
            ):
                continue
            station_specs = get_entity_specs(
                platform, scope=SCOPE_STATION, state=ride, caps=caps
            )
            if not station_specs:
                continue
            for station in Ride.from_cache(ride).stations:
                station_id = station.station_id
                if not station_id:
                    continue
                for spec in station_specs:
                    ident = (ride_key, spec.key, station_id)
                    out[ident] = (spec, ride_key, station_id)
        return out

    def _sync() -> None:
        wanted = _wanted()
        to_add: list[TrafficalEntity] = []
        for ident, (spec, ride_key, station_id) in wanted.items():
            if ident in known:
                continue
            entity = entity_factory(coordinator, spec, ride_key, station_id)
            known[ident] = entity
            to_add.append(entity)
        stale = [ident for ident in known if ident not in wanted]
        for ident in stale:
            entity = known.pop(ident)
            if getattr(entity, "hass", None) is not None:
                hass.async_create_task(entity.async_remove(force_remove=True))
        if stale:
            _LOGGER.debug(f"removing {len(stale)} entities on {platform}")
        if to_add:
            _LOGGER.debug(
                f"adding {len(to_add)} entities on {platform}: "
                f"{[entity.spec.key for entity in to_add]}"
            )
            async_add_entities(to_add)

    _sync()

    @callback
    def _on_specs_changed() -> None:
        _sync()

    unsub = coordinator.register_entity_listener(_on_specs_changed)
    entry.async_on_unload(unsub)
    return unsub
