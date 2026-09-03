"""HA base Traffical entity.

May import homeassistant. The HA-free catalog lives in ``models/entity_specs``
and value resolution in ``models/entity_values``.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..managers.coordinator import TrafficalCoordinator
from ..models.entity_specs import SCOPE_HUB, SCOPE_STATION, EntitySpec
from ..models.entity_values import EntityContext, EntityValueResolver
from .entity_descriptions import get_entity_description


class TrafficalEntity(CoordinatorEntity[TrafficalCoordinator]):
    """Coordinator entity backed by an EntitySpec on the hub or a ride device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TrafficalCoordinator,
        spec: EntitySpec,
        ride_key: str | None = None,
        station_id: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.spec = spec
        self.ride_key = ride_key
        self.station_id = station_id
        self._resolver = EntityValueResolver()
        self.entity_description = get_entity_description(spec)
        parts = [coordinator.hub_id]
        if ride_key:
            parts.append(ride_key)
        parts.append(spec.key)
        if station_id:
            parts.append(station_id)
        self._attr_unique_id = "_".join(parts)
        info = (
            coordinator.hub_device_info()
            if ride_key is None
            else coordinator.ride_device_info(ride_key)
        )
        self._attr_device_info = DeviceInfo(**info)

    @property
    def _entity_ctx(self) -> EntityContext:
        return self.coordinator.entity_context()

    def _state(self) -> dict[str, Any]:
        """The state slice this spec's scope resolves against."""
        if self.spec.scope == SCOPE_HUB:
            return self.coordinator.data or {}
        ride = dict(self.coordinator.ride(self.ride_key or ""))
        if self.spec.scope == SCOPE_STATION:
            return {
                "ride": ride,
                "ride_key": self.ride_key,
                "station_id": self.station_id,
            }
        return ride

    @property
    def available(self) -> bool:
        return self._resolver.is_available(self.spec, self._state(), self._entity_ctx)

    def _state_value(self) -> Any:
        return self._resolver.resolve_value(self.spec, self._state(), self._entity_ctx)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._resolver.resolve_attributes(
            self.spec, self._state(), self._entity_ctx
        )

    async def _async_send_action(self) -> None:
        if not self.spec.action:
            return
        await self.coordinator.async_action(self.spec.action, self.ride_key)
