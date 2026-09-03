"""HA-agnostic entity catalog. No homeassistant imports.

Every entity the integration exposes is declared here once. ``common/
entity_descriptions`` maps a spec to a Home Assistant ``EntityDescription`` and
``entity_values`` resolves its state; platforms only wire the two together.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

SCOPE_HUB = "hub"
SCOPE_RIDE = "ride"
SCOPE_STATION = "station"


@dataclass(frozen=True, kw_only=True)
class EntitySpec:
    """One entity: where it lives, how it is named, how its value is found."""

    key: str
    platform: str
    name: str
    scope: str = SCOPE_RIDE
    data_path: str | None = None  # dotted path into the scope's state dict
    resolve: str | None = None  # named value resolver
    attributes: str | None = None  # named attribute resolver
    options: tuple[str, ...] | None = None  # static select/enum options
    options_resolve: str | None = None  # named options resolver
    dynamic_name: str | None = None  # named name resolver (skips translation_key)
    icon_resolve: str | None = None  # named icon resolver, overrides icon
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    entity_category: str | None = None  # config | diagnostic
    enabled_default: bool = True  # False → user must enable in the entity registry
    when: str | None = None  # creation gate, e.g. policy:gotOnRideReport
    availability: str | None = None  # named availability rule
    action: str | None = None  # coordinator action for button presses

    def has_live_state(self) -> bool:
        """True if a value can be resolved for this spec."""
        return bool(self.data_path or self.resolve)

    def format_value(self, value: Any) -> str:
        if value is None:
            return "unknown"
        if self.unit:
            return f"{value} {self.unit}"
        return str(value)


ENTITY_SPECS: tuple[EntitySpec, ...] = (
    # --- account hub ---
    EntitySpec(
        key="next_ride",
        platform="sensor",
        name="Next ride",
        scope=SCOPE_HUB,
        resolve="next_ride",
        attributes="next_ride",
        icon="mdi:bus-clock",
    ),
    EntitySpec(
        key="refresh",
        platform="button",
        name="Refresh",
        scope=SCOPE_HUB,
        action="refresh",
        icon="mdi:refresh",
        entity_category="diagnostic",
    ),
    EntitySpec(
        key="child",
        platform="select",
        name="Child",
        scope=SCOPE_HUB,
        resolve="child_current",
        options_resolve="child_options",
        availability="multi_child",
        icon="mdi:account-child",
        entity_category="config",
    ),
    # --- per recurring ride ---
    EntitySpec(
        key="status",
        platform="sensor",
        name="Status",
        data_path="status",
        attributes="status",
        icon="mdi:bus-alert",
    ),
    EntitySpec(
        key="my_station",
        platform="sensor",
        name="My station",
        resolve="my_station",
        attributes="my_station",
        icon="mdi:bus-stop",
    ),
    EntitySpec(
        key="destination",
        platform="sensor",
        name="Destination",
        resolve="destination",
        attributes="destination",
        icon="mdi:map-marker-radius",
    ),
    EntitySpec(
        key="driver",
        platform="sensor",
        name="Driver",
        resolve="driver",
        icon="mdi:account",
    ),
    EntitySpec(
        key="vehicle",
        platform="sensor",
        name="Vehicle",
        resolve="vehicle",
        attributes="vehicle",
        icon="mdi:bus",
    ),
    EntitySpec(
        key="boarding_at",
        platform="sensor",
        name="Boarding",
        resolve="boarding_at",
        device_class="timestamp",
        icon="mdi:clock-start",
    ),
    EntitySpec(
        key="dropoff_at",
        platform="sensor",
        name="Drop-off",
        resolve="dropoff_at",
        device_class="timestamp",
        icon="mdi:clock-end",
    ),
    EntitySpec(
        key="checked_in",
        platform="binary_sensor",
        name="Checked in",
        resolve="checked_in",
        attributes="checked_in",
        icon="mdi:account-check",
    ),
    EntitySpec(
        key="check_in",
        platform="button",
        name="Check in",
        action="check_in",
        when="policy:gotOnRideReport",
        availability="can_check_in",
        icon="mdi:login",
        enabled_default=False,
    ),
    EntitySpec(
        key="check_out",
        platform="button",
        name="Check out",
        action="check_out",
        when="policy:gotOnRideReport",
        availability="can_check_out",
        icon="mdi:logout",
        enabled_default=False,
    ),
    EntitySpec(
        key="not_coming",
        platform="button",
        name="Not coming",
        action="not_coming",
        when="policy:notComingReport",
        availability="can_not_come",
        icon="mdi:account-off",
    ),
    EntitySpec(
        key="bus",
        platform="device_tracker",
        name="Bus",
        resolve="bus_position",
        availability="gps_live",
    ),
    EntitySpec(
        key="rides",
        platform="calendar",
        name="Rides",
        icon="mdi:calendar-clock",
    ),
    # --- per station of the focused ride ---
    EntitySpec(
        key="stop",
        platform="geo_location",
        name="Stop",
        scope=SCOPE_STATION,
        resolve="station_position",
        attributes="station",
        dynamic_name="station_label",
        icon_resolve="station_icon",
        availability="focus_station",
    ),
)


def policy_active(policies: Any, group: str) -> bool:
    """Whether a passenger policy group is enabled for this tenant."""
    if not isinstance(policies, Mapping):
        return False
    block = policies.get(group)
    if not isinstance(block, Mapping):
        return False
    return bool(block.get("isActive"))


def _when_ok(when: str | None, caps: Mapping[str, Any]) -> bool:
    if not when:
        return True
    if when.startswith("policy:"):
        return policy_active(caps.get("policies"), when.split(":", 1)[1])
    if when.startswith("!policy:"):
        return not policy_active(caps.get("policies"), when.split(":", 1)[1])
    return True


def get_entity_specs(
    platform: str | None = None,
    *,
    scope: str | None = None,
    state: Mapping[str, Any] | None = None,
    caps: Mapping[str, Any] | None = None,
) -> list[EntitySpec]:
    """Specs for a platform, filtered by scope and tenant capabilities."""
    caps = caps or {}
    out: list[EntitySpec] = []
    for spec in ENTITY_SPECS:
        if platform and spec.platform != platform:
            continue
        if scope and spec.scope != scope:
            continue
        if not _when_ok(spec.when, caps):
            continue
        out.append(spec)
    return out


def spec_as_dict(spec: EntitySpec) -> dict[str, Any]:
    data = asdict(spec)
    if data.get("options") is not None:
        data["options"] = list(data["options"])
    return data
