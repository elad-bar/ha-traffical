"""Traffical buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.entity_descriptions import HUB_BUTTONS, RIDE_BUTTONS
from .common.entity_setup import async_setup_entities
from .managers.coordinator import TrafficalCoordinator
from .models.rides import status_finished, status_live

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
        HUB_BUTTONS,
        RIDE_BUTTONS,
        TrafficalButton,
    )


class TrafficalButton(TrafficalEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self.entity_key == "refresh":
            return True
        ride = self.coordinator.ride(self.ride_key or "")
        status = str(ride.get("status") or "")
        check = ride.get("checkin") if isinstance(ride.get("checkin"), dict) else {}
        checked = bool(check.get("checkIn")) if check else False
        if self.entity_key == "check_in":
            if not self.coordinator.policy_active("gotOnRideReport"):
                return False
            return (
                not status_finished(status)
                and not checked
                and (status_live(status) or status.casefold() == "new")
            )
        if self.entity_key == "check_out":
            if not self.coordinator.policy_active("gotOnRideReport"):
                return False
            return checked and not status_finished(status)
        if self.entity_key == "not_coming":
            if not self.coordinator.policy_active("notComingReport"):
                return False
            return status.casefold() == "new"
        return True

    async def async_press(self) -> None:
        if self.entity_key == "refresh":
            await self.coordinator.async_request_refresh()
            return
        if self.ride_key is None:
            return
        if self.entity_key == "check_in":
            await self.coordinator.async_check_in(self.ride_key, True)
        elif self.entity_key == "check_out":
            await self.coordinator.async_check_in(self.ride_key, False)
        elif self.entity_key == "not_coming":
            await self.coordinator.async_not_coming(self.ride_key)
