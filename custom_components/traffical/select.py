"""Traffical child select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .managers.coordinator import TrafficalCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TrafficalCoordinator = entry.runtime_data
    async_add_entities([TrafficalChildSelect(coordinator, "child")])


class TrafficalChildSelect(TrafficalEntity, SelectEntity):
    @property
    def options(self) -> list[str]:
        children = (self.coordinator.data or {}).get("children") or []
        opts = [self._label(c) for c in children]
        if not opts:
            person = (self.coordinator.store.user or {}).get("person") or {}
            name = " ".join(
                p for p in (person.get("firstName"), person.get("lastName")) if p
            )
            return [name or "passenger"]
        return opts

    @property
    def current_option(self) -> str | None:
        person = (self.coordinator.store.user or {}).get("person") or {}
        member_id = person.get("memberId")
        for child in (self.coordinator.data or {}).get("children") or []:
            if child.get("memberId") == member_id:
                return self._label(child)
        opts = self.options
        return opts[0] if opts else None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        children = (self.coordinator.data or {}).get("children") or []
        return len(children) > 1

    async def async_select_option(self, option: str) -> None:
        for child in (self.coordinator.data or {}).get("children") or []:
            if self._label(child) == option:
                await self.coordinator.async_switch_child(str(child.get("memberId")))
                return

    def _label(self, child: dict) -> str:
        name = " ".join(
            p for p in (child.get("firstName"), child.get("lastName")) if p
        )
        return name or str(child.get("memberId"))
