"""Diagnostics for Traffical config entries and devices."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .common.consts import DOMAIN
from .common.helpers import partial_id
from .managers.coordinator import TrafficalCoordinator
from .models.rides import Ride, rides_customer_type, status_live

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
    "ticket",
    "name",
    "displayName",
    "address",
    "phoneNumber",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _entry_block(entry: ConfigEntry) -> dict[str, Any]:
    return {
        "title": entry.title,
        "domain": entry.domain,
        "unique_id": entry.unique_id,
        "data": async_redact_data(_json_safe(dict(entry.data)), TO_REDACT),
        "options": _json_safe(dict(entry.options)),
    }


def _token_flags(tokens: dict[str, Any] | None) -> dict[str, Any]:
    tokens = tokens if isinstance(tokens, dict) else {}
    return {
        "access_token_present": bool(tokens.get("access_token")),
        "refresh_token_present": bool(tokens.get("refresh_token")),
        "expires_in": tokens.get("expires_in"),
        "obtained_at": tokens.get("obtained_at"),
    }


def _store_block(coordinator: TrafficalCoordinator) -> dict[str, Any]:
    store = coordinator.store
    return {
        "environment": store.environment,
        "api_url": store.api_url,
        "identity_url": store.identity_url,
        "language": store.language,
        "device_id": store.device_id,
        "child_id": store.child_id or None,
        **_token_flags(store.tokens),
    }


def _merge_query_logs(
    coordinator: TrafficalCoordinator, ride_id: int | str | None = None
) -> dict[str, Any]:
    account: dict[str, Any] = {}
    rides: dict[str, Any] = {}
    for client in (coordinator.identity, coordinator.mobile):
        getter = getattr(client, "query_log_for_diagnostics", None)
        if not callable(getter):
            continue
        raw = getter(ride_id)
        if not isinstance(raw, dict):
            continue
        account.update(raw.get("account") or {})
        for rid, bucket in (raw.get("rides") or {}).items():
            rides.setdefault(str(rid), {}).update(
                bucket if isinstance(bucket, dict) else {}
            )
    return {"account": account, "rides": rides}


def _policy_flags(coordinator: TrafficalCoordinator) -> dict[str, bool]:
    policies = (coordinator.data or {}).get("policies") or {}
    if not isinstance(policies, dict):
        return {}
    return {str(group): coordinator.policy_active(str(group)) for group in policies}


def _account_details(coordinator: TrafficalCoordinator) -> dict[str, Any]:
    data = coordinator.data or {}
    customer = (coordinator.store.user or {}).get("customer") or {}
    children = data.get("children") or []
    interval = coordinator.update_interval
    last_exc = getattr(coordinator, "last_exception", None)
    return {
        "hub_id": partial_id(coordinator.hub_id),
        "session_ok": bool(data.get("session_ok")),
        "reauth_started": bool(getattr(coordinator, "_reauth_started", False)),
        "token_present": bool(coordinator.store.tokens.get("access_token")),
        "environment": coordinator.store.environment,
        "language": coordinator.store.language,
        "customer_type": rides_customer_type(customer.get("type")),
        "children_count": len(children) if isinstance(children, list) else 0,
        "member_id_present": coordinator.member_id() is not None,
        "policies": _policy_flags(coordinator),
        "last_update_success": bool(getattr(coordinator, "last_update_success", False)),
        "last_exception": str(last_exc) if last_exc else None,
        "update_interval": interval.total_seconds() if interval else None,
        "live_key": data.get("live_key"),
        "focus_ride_key": data.get("focus_ride_key"),
    }


def _ride_summary(
    coordinator: TrafficalCoordinator, key: str, ride: dict[str, Any]
) -> dict[str, Any]:
    model = Ride.from_cache(ride)
    check = ride.get("checkin") if isinstance(ride.get("checkin"), dict) else {}
    start = model.start
    your = model.your_station(coordinator.member_id())
    passed = ride.get("passed_stations") or []
    try:
        passed_count = len(passed)
    except TypeError:
        passed_count = 0
    return {
        "route_id": ride.get("route_id"),
        "direction": ride.get("direction"),
        "ride_id": ride.get("ride_id"),
        "status": ride.get("status"),
        "assigned_today": bool(ride.get("assigned_today")),
        "ticket_present": bool(ride.get("ticket") or model.ticket),
        "check_in": check.get("checkIn") if check else None,
        "check_in_at": check.get("checkInAt") if check else None,
        "start_time": start.isoformat() if start else None,
        "station_count": len(model.stations),
        "passed_station_count": passed_count,
        "has_your_station": your is not None,
        "has_fix": ride.get("lat") is not None,
        "approaching_fired": bool(ride.get("approaching_fired")),
        "is_live": status_live(str(ride.get("status") or "")),
        "is_focus": key == (coordinator.data or {}).get("focus_ride_key"),
    }


def _rides_block(
    coordinator: TrafficalCoordinator,
    logs: dict[str, Any],
    ride_keys: list[str] | None,
) -> dict[str, Any]:
    rides = (coordinator.data or {}).get("rides") or {}
    keys = ride_keys if ride_keys is not None else list(rides)
    per = logs.get("rides") or {}
    out: dict[str, Any] = {}
    for key in keys:
        ride = rides.get(key) or {}
        ride_id = ride.get("ride_id")
        out[key] = {
            "details": _ride_summary(coordinator, key, ride),
            "api": per.get(str(ride_id)) or {},
        }
    return out


def _unique_id_for_ride(hub_id: str, ride_key: str) -> str:
    return f"{hub_id}_{ride_key}_"


def _registry_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: TrafficalCoordinator,
    ride_keys: list[str] | None,
) -> dict[str, list[dict[str, Any]]]:
    registry = er.async_get(hass)
    hub_id = coordinator.hub_id
    all_ride_keys = list(coordinator.ride_keys)
    wanted = all_ride_keys if ride_keys is None else ride_keys
    grouped: dict[str, list[dict[str, Any]]] = {"hub": []} if ride_keys is None else {}
    for key in wanted:
        grouped[key] = []
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = ent.unique_id or ""
        bucket: str | None = None
        for ride_key in all_ride_keys:
            prefix = _unique_id_for_ride(hub_id, ride_key)
            if unique_id.startswith(prefix):
                bucket = ride_key
                break
        if bucket is None:
            if ride_keys is not None:
                continue
            if unique_id.startswith(f"{hub_id}_"):
                bucket = "hub"
            else:
                continue
        if bucket not in grouped:
            continue
        st = hass.states.get(ent.entity_id)
        row: dict[str, Any] = {
            "entity_id": ent.entity_id,
            "unique_id": unique_id,
            "platform": ent.platform,
            "disabled_by": ent.disabled_by,
            "state": st.state if st is not None else None,
        }
        if st is not None:
            row["attributes"] = async_redact_data(
                _json_safe(dict(st.attributes)), TO_REDACT
            )
        grouped[bucket].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: item["entity_id"])
    return grouped


def _signalr_block(
    coordinator: TrafficalCoordinator, ride_id: int | None
) -> dict[str, Any]:
    hubs = coordinator.hubs
    getter = getattr(hubs, "snapshot_for_diagnostics", None)
    if not callable(getter):
        return {}
    raw = getter()
    if not isinstance(raw, dict):
        return {}
    if ride_id is None:
        return raw
    out: dict[str, Any] = {"mobile": raw.get("mobile") or {}}
    dashboard = raw.get("dashboard") or {}
    tracked = dashboard.get("track_ride_id")
    if tracked is not None and int(tracked) == int(ride_id):
        out["dashboard"] = dashboard
    return out


def _diagnostics_payload(
    hass: HomeAssistant | None,
    entry: ConfigEntry,
    coordinator: TrafficalCoordinator,
    *,
    ride_key: str | None = None,
) -> dict[str, Any]:
    ride_keys = [ride_key] if ride_key else None
    ride_id = None
    if ride_key:
        ride = coordinator.ride(ride_key)
        ride_id = ride.get("ride_id")
    logs = _merge_query_logs(coordinator, ride_id)
    entities: dict[str, list[dict[str, Any]]] = {}
    if hass is not None:
        entities = _registry_entities(hass, entry, coordinator, ride_keys)
    return _json_safe(
        {
            "entry": _entry_block(entry),
            "store": _store_block(coordinator),
            "account": {
                "details": _account_details(coordinator),
                "api": logs.get("account") or {},
                "signalr": _signalr_block(coordinator, ride_id if ride_key else None),
            },
            "rides": _rides_block(coordinator, logs, ride_keys),
            "entities": entities,
        }
    )


def _ride_key_from_device(
    device: DeviceEntry, hub_id: str
) -> tuple[str | None, str | None]:
    """Return (kind, ride_key). kind is hub, ride, or None if unknown."""
    for domain, ident in device.identifiers:
        if domain != DOMAIN:
            continue
        text = str(ident)
        if text == hub_id:
            return "hub", None
        prefix = f"{hub_id}:"
        if text.startswith(prefix):
            return "ride", text[len(prefix) :]
        if ":" in text:
            return "ride", text.split(":", 1)[1]
    return None, None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: TrafficalCoordinator | None = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {"entry": _entry_block(entry)}
    return _diagnostics_payload(hass, entry, coordinator)


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for the account hub or one ride device."""
    coordinator: TrafficalCoordinator | None = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {"error": "unknown_device", "entry": _entry_block(entry)}
    kind, ride_key = _ride_key_from_device(device, coordinator.hub_id)
    if kind is None:
        return {"error": "unknown_device"}
    if kind == "hub":
        return _diagnostics_payload(hass, entry, coordinator)
    if ride_key not in coordinator.ride_keys:
        return {"error": "unknown_device"}
    return _diagnostics_payload(hass, entry, coordinator, ride_key=ride_key)
