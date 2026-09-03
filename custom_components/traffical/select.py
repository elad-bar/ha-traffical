"""Traffical selects."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.entity_setup import async_setup_entities
from .managers.coordinator import TrafficalCoordinator
from .models.entity_values import child_id_for_label

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TrafficalCoordinator = entry.runtime_data
    async_setup_entities(
        hass, entry, coordinator, "select", async_add_entities, TrafficalSelect
    )


class TrafficalSelect(TrafficalEntity, SelectEntity):
    @property
    def options(self) -> list[str]:
        return self._resolver.resolve_options(
            self.spec, self._state(), self._entity_ctx
        )

    @property
    def current_option(self) -> str | None:
        return self._state_value()

    async def async_select_option(self, option: str) -> None:
        child_id = child_id_for_label(option, self._entity_ctx)
        if child_id is None:
            return
        await self.coordinator.async_switch_child(child_id)
