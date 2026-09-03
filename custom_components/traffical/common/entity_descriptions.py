"""Map HA-free EntitySpec → Home Assistant EntityDescription subclasses.

May import homeassistant. Platforms should use descriptions from here rather
than building HA attributes from the catalog directly.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.calendar import CalendarEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfTime
from homeassistant.helpers.entity import EntityCategory, EntityDescription

from ..models.entity_specs import EntitySpec

_SENSOR_DEVICE_CLASS = {v.value: v for v in SensorDeviceClass}
_SENSOR_STATE_CLASS = {v.value: v for v in SensorStateClass}
_BINARY_DEVICE_CLASS = {v.value: v for v in BinarySensorDeviceClass}

_ENTITY_CATEGORY = {
    "config": EntityCategory.CONFIG,
    "diagnostic": EntityCategory.DIAGNOSTIC,
}

_UNIT_MAP: dict[str, str] = {
    "m": UnitOfLength.METERS,
    "km": UnitOfLength.KILOMETERS,
    "min": UnitOfTime.MINUTES,
    "s": UnitOfTime.SECONDS,
    "%": PERCENTAGE,
}


def _map_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return _UNIT_MAP.get(unit, unit)


def get_entity_description(spec: EntitySpec) -> EntityDescription:
    """Build the HA EntityDescription for a catalog spec."""
    base: dict = {"key": spec.key}
    # Stations are named from live data, so they carry no translation key.
    if spec.dynamic_name is None:
        base["translation_key"] = spec.key
    if spec.icon:
        base["icon"] = spec.icon
    if spec.entity_category:
        category = _ENTITY_CATEGORY.get(spec.entity_category)
        if category is not None:
            base["entity_category"] = category
    if not spec.enabled_default:
        base["entity_registry_enabled_default"] = False

    platform = spec.platform
    if platform == "sensor":
        kwargs = dict(base)
        unit = _map_unit(spec.unit)
        if unit:
            kwargs["native_unit_of_measurement"] = unit
        if spec.device_class:
            kwargs["device_class"] = _SENSOR_DEVICE_CLASS.get(spec.device_class)
        if spec.state_class:
            kwargs["state_class"] = _SENSOR_STATE_CLASS.get(spec.state_class)
        if spec.options:
            kwargs["options"] = list(spec.options)
        return SensorEntityDescription(**kwargs)

    if platform == "binary_sensor":
        kwargs = dict(base)
        if spec.device_class:
            kwargs["device_class"] = _BINARY_DEVICE_CLASS.get(spec.device_class)
        return BinarySensorEntityDescription(**kwargs)

    if platform == "button":
        return ButtonEntityDescription(**base)
    if platform == "calendar":
        return CalendarEntityDescription(**base)
    if platform == "select":
        return SelectEntityDescription(**base)

    return EntityDescription(**base)
