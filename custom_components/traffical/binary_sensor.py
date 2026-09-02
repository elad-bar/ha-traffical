"""Traffical binary sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.entity_descriptions import HUB_BINARY, RIDE_BINARY
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
        async_add_entities,
        HUB_BINARY,
        RIDE_BINARY,
        TrafficalBinarySensor,
    )


class TrafficalBinarySensor(TrafficalEntity, BinarySensorEntity):
    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        if self.entity_key == "session":
            return BinarySensorDeviceClass.CONNECTIVITY
        return None

    @property
    def is_on(self) -> bool | None:
        if self.entity_key == "session":
            return bool((self.coordinator.data or {}).get("session_ok"))
        ride = self.coordinator.ride(self.ride_key or "")
        check = ride.get("checkin")
        if not isinstance(check, dict) or check.get("checkIn") is None:
            return None
        return bool(check.get("checkIn"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.entity_key != "checked_in" or not self.ride_key:
            return {}
        check = self.coordinator.ride(self.ride_key).get("checkin") or {}
        if not isinstance(check, dict):
            return {}
        return {"check_in_at": check.get("checkInAt")}
