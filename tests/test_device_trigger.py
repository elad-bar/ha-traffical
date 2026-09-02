"""Device trigger listing for ride vs hub devices."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.traffical.common.consts import DOMAIN
from custom_components.traffical.device_trigger import TRIGGER_TYPES, async_get_triggers
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

_HUB = "user-sub-1"
_RIDE_KEY = "392681:120"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id=_HUB, data={})


@pytest.mark.asyncio
async def test_triggers_on_ride_device_not_hub(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    hub = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, _HUB)},
        manufacturer="Traffical",
        name="Traffical · School",
        model="Account",
    )
    ride = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{_HUB}:{_RIDE_KEY}")},
        via_device=(DOMAIN, _HUB),
        manufacturer="Traffical",
        name="Morning",
        model="Ride",
    )
    assert await async_get_triggers(hass, hub.id) == []
    triggers = await async_get_triggers(hass, ride.id)
    types = {item["type"] for item in triggers}
    assert types == set(TRIGGER_TYPES)
    for item in triggers:
        assert item["platform"] == "device"
        assert item["domain"] == DOMAIN
        assert item["device_id"] == ride.id
