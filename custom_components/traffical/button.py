"""Traffical buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
        hass, entry, coordinator, "button", async_add_entities, TrafficalButton
    )


class TrafficalButton(TrafficalEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self._async_send_action()
