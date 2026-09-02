"""Device triggers for Traffical ride devices."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .common.consts import (
    DOMAIN,
    EVENT_APPROACHING_STOP,
    EVENT_ARRIVED_STATION,
    EVENT_CHECKIN_CHANGED,
    EVENT_RIDE_FINISHED,
    EVENT_RIDE_STARTED,
    EVENT_RIDE_STATUS_CHANGED,
)

TRIGGER_TYPES = {
    "ride_status_changed": EVENT_RIDE_STATUS_CHANGED,
    "ride_started": EVENT_RIDE_STARTED,
    "ride_finished": EVENT_RIDE_FINISHED,
    "checkin_changed": EVENT_CHECKIN_CHANGED,
    "arrived_station": EVENT_ARRIVED_STATION,
    "approaching_stop": EVENT_APPROACHING_STOP,
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES)}
)


def ride_key_from_device(hass: HomeAssistant, device_id: str) -> str | None:
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        return None
    for domain, ident in device.identifiers:
        if domain != DOMAIN or ":" not in ident:
            continue
        return ident.split(":", 1)[1]
    return None


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    if ride_key_from_device(hass, device_id) is None:
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in TRIGGER_TYPES
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    config = TRIGGER_SCHEMA(config)
    ride_key = ride_key_from_device(hass, config[CONF_DEVICE_ID])
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: TRIGGER_TYPES[config[CONF_TYPE]],
            event_trigger.CONF_EVENT_DATA: {"key": ride_key} if ride_key else {},
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
