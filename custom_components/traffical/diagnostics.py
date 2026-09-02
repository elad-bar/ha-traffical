"""Diagnostics for Traffical config entries."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .managers.coordinator import TrafficalCoordinator

TO_REDACT = {
    "access_token",
    "refresh_token",
    "id_token",
    "phone",
    "otp",
    "otp_ticket",
    "tokens",
    "latitude",
    "longitude",
    "lat",
    "lng",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: TrafficalCoordinator = entry.runtime_data
    rides = {}
    for key, ride in (coordinator.data.get("rides") or {}).items():
        rides[key] = {
            "route_id": ride.get("route_id"),
            "direction": ride.get("direction"),
            "ride_id": ride.get("ride_id"),
            "status": ride.get("status"),
            "assigned_today": ride.get("assigned_today"),
            "has_fix": ride.get("lat") is not None,
        }
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "hub_id": coordinator.hub_id,
        "session_ok": (coordinator.data or {}).get("session_ok"),
        "live_key": (coordinator.data or {}).get("live_key"),
        "focus_ride_key": (coordinator.data or {}).get("focus_ride_key"),
        "rides": rides,
    }
