"""HA base Traffical entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..managers.coordinator import TrafficalCoordinator


class TrafficalEntity(CoordinatorEntity[TrafficalCoordinator]):
    """Coordinator entity on the account hub or a ride device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TrafficalCoordinator,
        key: str,
        ride_key: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_key = key
        self.ride_key = ride_key
        self._attr_translation_key = key
        if ride_key:
            self._attr_unique_id = f"{coordinator.hub_id}_{ride_key}_{key}"
            info = coordinator.ride_device_info(ride_key)
        else:
            self._attr_unique_id = f"{coordinator.hub_id}_{key}"
            info = coordinator.hub_device_info()
        self._attr_device_info = DeviceInfo(**info)

    @property
    def available(self) -> bool:
        if not self.coordinator.data or not self.coordinator.data.get("session_ok"):
            return False
        if self.ride_key is None:
            return True
        ride = self.coordinator.ride(self.ride_key)
        return bool(ride.get("assigned_today"))
