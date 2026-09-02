"""Traffical data coordinator — HTTP poll + auto SignalR."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..common.consts import (
    CONF_POLL_INTERVAL,
    DOMAIN,
    EVENT_APPROACHING_STOP,
    EVENT_ARRIVED_STATION,
    EVENT_CHECKIN_CHANGED,
    EVENT_RIDE_FINISHED,
    EVENT_RIDE_STARTED,
    EVENT_RIDE_STATUS_CHANGED,
    FAST_WINDOW,
    MANUFACTURER,
    POLL_INTERVAL,
    POLL_INTERVAL_FAST,
)
from ..common.helpers import client_session, parse_utc, partial_id
from ..models.exceptions import ApiError, AuthError
from ..models.rides import (
    coord_from_payload,
    is_your_station,
    list_row_ids,
    list_row_route_key,
    ride_name,
    rides_customer_type,
    station_id,
    status_finished,
    status_live,
)
from .identity_client import IdentityClient
from .mobile_client import MobileClient
from .signalr_client import SignalRHubs
from .store import SessionStore

_LOGGER = logging.getLogger(__name__)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class TrafficalCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll rides and attach SignalR while a ride is live."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: SessionStore,
        identity: IdentityClient,
        mobile: MobileClient,
        hubs: SignalRHubs,
        session,
    ) -> None:
        interval = entry.options.get(CONF_POLL_INTERVAL)
        update_interval = (
            timedelta(seconds=int(interval)) if interval else POLL_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.entry = entry
        self.store = store
        self.identity = identity
        self.mobile = mobile
        self.hubs = hubs
        self._session = session
        self._reauth_started = False
        self._ride_listener: Callable[[], None] | None = None
        self.data: dict[str, Any] = {
            "rides": {},
            "user": {},
            "policies": {},
            "children": [],
            "session_ok": False,
            "live_key": None,
        }
        self.identity.on_unauthorized = self._on_unauthorized
        self.mobile.on_unauthorized = self._on_unauthorized

    @property
    def hub_id(self) -> str:
        user = self.store.user or {}
        return str(user.get("sub") or self.store.phone or self.entry.entry_id)

    @property
    def ride_keys(self) -> list[str]:
        rides = self.data.get("rides") or {}
        return list(rides)

    def ride(self, key: str) -> dict[str, Any]:
        rides = self.data.get("rides") or {}
        return rides.get(key) or {}

    def member_id(self) -> int | None:
        person = (self.store.user or {}).get("person") or {}
        try:
            return int(person.get("memberId"))
        except (TypeError, ValueError):
            return None

    def policy_active(self, group: str) -> bool:
        policies = self.data.get("policies") or {}
        block = policies.get(group) or {}
        if isinstance(block, dict):
            return bool(block.get("isActive"))
        return False

    async def async_start(self) -> None:
        _LOGGER.info("coordinator starting")
        await self.async_config_entry_first_refresh()
        self._register_devices()

    async def async_stop(self) -> None:
        _LOGGER.info("coordinator stopping")
        await self.hubs.stop_track()
        await self._session.close()

    def register_entity_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._ride_listener = listener

        def _unsub() -> None:
            if self._ride_listener == listener:
                self._ride_listener = None

        return _unsub

    def _notify_entities(self) -> None:
        if self._ride_listener is not None:
            self._ride_listener()

    async def _on_unauthorized(self) -> bool:
        return await self._refresh_tokens()

    async def _refresh_tokens(self) -> bool:
        refresh = self.store.tokens.get("refresh_token")
        if not refresh:
            await self._start_reauth()
            return False
        try:
            body = await self.identity.refresh(refresh)
        except (ApiError, AuthError):
            _LOGGER.warning("auth failure source=refresh")
            await self._start_reauth()
            return False
        self.store.set_tokens(body)
        self._persist_entry()
        _LOGGER.info("Access token refreshed")
        return True

    def _persist_entry(self) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, **self.store.persist_fields()}
        )

    async def _start_reauth(self) -> None:
        if self._reauth_started:
            return
        self._reauth_started = True
        _LOGGER.error(f"starting reauth flow entry_id={partial_id(self.entry.entry_id)}")
        self.entry.async_start_reauth(self.hass)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._poll()
        except PermissionError as exc:
            await self._start_reauth()
            raise ConfigEntryAuthFailed from exc
        except ApiError as exc:
            if exc.status_code in (400, 401):
                await self._start_reauth()
                raise ConfigEntryAuthFailed from exc
            raise UpdateFailed(str(exc)) from exc

    async def _ensure_session(self) -> None:
        if not self.store.tokens.get("access_token"):
            raise ConfigEntryAuthFailed("no tokens")
        try:
            user = await self.identity.userinfo()
        except PermissionError:
            if not await self._refresh_tokens():
                raise ConfigEntryAuthFailed("refresh failed") from None
            user = await self.identity.userinfo()
        self.store.set_user(user)
        self._persist_entry()

    async def _poll(self) -> dict[str, Any]:
        await self._ensure_session()
        try:
            roles = await self.mobile.user_roles()
        except ApiError:
            roles = self.store.data.get("roles") or []
        self.store.set_roles(roles)
        try:
            policies = await self.mobile.passenger_policies()
        except ApiError:
            policies = self.store.data.get("policies") or {}
        if not isinstance(policies, dict):
            policies = {}
        self.store.set_policies(policies)
        children = self._children_from_roles(roles)
        customer = (self.store.user or {}).get("customer") or {}
        customer_type = rides_customer_type(customer.get("type"))
        date_str = date.today().isoformat()
        rides_raw = await self.mobile.list_rides(customer_type, date_str)
        if not isinstance(rides_raw, list):
            rides_raw = []
        ride_ids: list[int] = []
        for row in rides_raw:
            _ticket, ride_id = list_row_ids(row)
            if ride_id is not None:
                ride_ids.append(ride_id)
        statuses: dict[int, dict[str, Any]] = {}
        if ride_ids:
            raw_status = await self.mobile.checkin_statuses(ride_ids)
            if isinstance(raw_status, list):
                for item in raw_status:
                    if not isinstance(item, dict):
                        continue
                    try:
                        statuses[int(item.get("rideId"))] = item
                    except (TypeError, ValueError):
                        pass
        previous = (self.data.get("rides") if self.data else None) or {}
        rides: dict[str, dict[str, Any]] = {k: dict(v) for k, v in previous.items()}
        for key, ride in rides.items():
            ride["assigned_today"] = False
        live_key: str | None = None
        for row in rides_raw:
            ticket, ride_id = list_row_ids(row)
            details: dict[str, Any] = {}
            if ticket:
                loaded = await self.mobile.ride_details(ticket)
                if isinstance(loaded, dict):
                    details = loaded
                    if ride_id is None:
                        try:
                            ride_id = int(details.get("rideId"))
                        except (TypeError, ValueError):
                            ride_id = None
            key = list_row_route_key(row, details)
            if key is None:
                continue
            old = previous.get(key) or {}
            status = str(details.get("status") or row.get("status") or "")
            old_status = str(old.get("status") or "")
            check = statuses.get(ride_id) if ride_id is not None else None
            passed = set(old.get("passed_stations") or [])
            lat = old.get("lat")
            lng = old.get("lng")
            rides[key] = {
                "key": key,
                "route_id": details.get("routeId") or row.get("routeId"),
                "direction": details.get("direction") or row.get("direction"),
                "ride_id": ride_id,
                "ticket": ticket,
                "name": ride_name(row, details),
                "status": status,
                "list_row": row,
                "details": details,
                "checkin": check,
                "assigned_today": True,
                "lat": lat,
                "lng": lng,
                "passed_stations": passed,
                "approaching_fired": bool(old.get("approaching_fired")),
            }
            self._emit_status(key, old_status, status, ride_id, details, row)
            self._emit_checkin(key, old.get("checkin"), check, ride_id)
            if status_live(status):
                live_key = key
        _LOGGER.info(f"ride list refreshed count={sum(1 for r in rides.values() if r.get('assigned_today'))}")
        self._adjust_interval(rides)
        data = {
            "rides": rides,
            "user": self.store.user,
            "policies": policies,
            "children": children,
            "session_ok": True,
            "live_key": live_key,
        }
        self.data = data
        self._register_devices()
        await self._sync_signalr(live_key, rides)
        self._notify_entities()
        return data

    def _children_from_roles(self, roles: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not isinstance(roles, list):
            return out
        for group in roles:
            if not isinstance(group, dict):
                continue
            kids = group.get("childrens") or group.get("children") or []
            if not isinstance(kids, list):
                continue
            for child in kids:
                if isinstance(child, dict) and child.get("memberId") is not None:
                    out.append(child)
        return out

    def _emit_status(
        self,
        key: str,
        old_status: str,
        new_status: str,
        ride_id: int | None,
        details: dict[str, Any],
        row: dict[str, Any],
    ) -> None:
        if not new_status or new_status == old_status:
            return
        direction = details.get("direction") or row.get("direction")
        self.hass.bus.async_fire(
            EVENT_RIDE_STATUS_CHANGED,
            {
                "ride_id": ride_id,
                "old": old_status,
                "new": new_status,
                "direction": direction,
                "key": key,
            },
        )
        if status_live(new_status) and not status_live(old_status):
            self.hass.bus.async_fire(
                EVENT_RIDE_STARTED,
                {"ride_id": ride_id, "name": ride_name(row, details)},
            )
        if status_finished(new_status) and not status_finished(old_status):
            self.hass.bus.async_fire(
                EVENT_RIDE_FINISHED,
                {"ride_id": ride_id, "checked_in": None},
            )

    def _emit_checkin(
        self, key: str, old: Any, new: Any, ride_id: int | None
    ) -> None:
        old_flag = old.get("checkIn") if isinstance(old, dict) else None
        new_flag = new.get("checkIn") if isinstance(new, dict) else None
        if new is None or new_flag == old_flag:
            return
        self.hass.bus.async_fire(
            EVENT_CHECKIN_CHANGED,
            {
                "ride_id": ride_id,
                "check_in": new_flag,
                "check_in_at": new.get("checkInAt") if isinstance(new, dict) else None,
                "key": key,
            },
        )

    def _adjust_interval(self, rides: dict[str, dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc)
        fast = False
        for ride in rides.values():
            if not ride.get("assigned_today"):
                continue
            details = ride.get("details") or {}
            info = (ride.get("list_row") or {}).get("rideInfo") or {}
            start = parse_utc(details.get("startTime") or info.get("startDateTime"))
            if start and timedelta(0) <= (start - now) <= FAST_WINDOW:
                fast = True
            if status_live(str(ride.get("status") or "")):
                fast = True
        wanted = POLL_INTERVAL_FAST if fast else POLL_INTERVAL
        option = self.entry.options.get(CONF_POLL_INTERVAL)
        if option:
            wanted = timedelta(seconds=int(option))
        if self.update_interval != wanted:
            self.update_interval = wanted

    async def _sync_signalr(
        self, live_key: str | None, rides: dict[str, dict[str, Any]]
    ) -> None:
        if live_key is None:
            if self.hubs.track_ride_id is not None:
                await self.hubs.stop_track()
            return
        ride = rides.get(live_key) or {}
        ride_id = ride.get("ride_id")
        if ride_id is None:
            return
        if self.hubs.track_ride_id == ride_id:
            return
        try:
            path = await self.mobile.monitoring_path(int(ride_id))
        except ApiError:
            path = []
        self._seed_path(live_key, path)
        _LOGGER.debug(f"Monitor invoke rideId={ride_id}")
        await self.hubs.start_track(int(ride_id), self._on_hub_event)
        _LOGGER.info(f"SignalR connected rideId={ride_id}")

    def _seed_path(self, key: str, path: Any) -> None:
        points = path if isinstance(path, list) else [path] if path else []
        if not points:
            return
        last = points[-1]
        lat, lng = coord_from_payload(last)
        ride = (self.data.get("rides") or {}).get(key)
        if ride is not None and lat is not None:
            ride["lat"] = lat
            ride["lng"] = lng

    async def _on_hub_event(self, event: str, payload: Any) -> None:
        live_key = (self.data or {}).get("live_key")
        if not live_key:
            return
        rides = self.data.get("rides") or {}
        ride = rides.get(live_key)
        if ride is None:
            return
        if event == "ReceiveCoordinates":
            lat, lng = coord_from_payload(payload)
            if lat is not None:
                ride["lat"] = lat
                ride["lng"] = lng
                self._maybe_approaching(live_key, ride)
                self.async_set_updated_data(self.data)
            return
        if event == "ArrivedToStation":
            sid = None
            if isinstance(payload, dict):
                sid = payload.get("stationId")
            else:
                sid = payload
            if sid is not None:
                passed = set(ride.get("passed_stations") or [])
                passed.add(str(sid))
                ride["passed_stations"] = passed
            member_id = self.member_id()
            details = ride.get("details") or {}
            info = (ride.get("list_row") or {}).get("rideInfo") or {}
            stop = str(info.get("passengerStationName") or "")
            is_mine = False
            for station in details.get("stations") or []:
                if not isinstance(station, dict):
                    continue
                if str(station_id(station) or "") == str(sid) and is_your_station(
                    station, stop, member_id
                ):
                    is_mine = True
                    break
            self.hass.bus.async_fire(
                EVENT_ARRIVED_STATION,
                {
                    "ride_id": ride.get("ride_id"),
                    "station_id": sid,
                    "is_my_station": is_mine,
                },
            )
            self.async_set_updated_data(self.data)

    def _maybe_approaching(self, key: str, ride: dict[str, Any]) -> None:
        if ride.get("approaching_fired"):
            return
        lat, lng = ride.get("lat"), ride.get("lng")
        if lat is None or lng is None:
            return
        home = self._home_station(ride)
        if home is None:
            return
        hlat, hlng = home
        distance = _haversine_m(float(lat), float(lng), hlat, hlng)
        if distance > 80:
            return
        ride["approaching_fired"] = True
        self.hass.bus.async_fire(
            EVENT_APPROACHING_STOP,
            {"ride_id": ride.get("ride_id"), "distance_m": int(distance)},
        )

    def _home_station(self, ride: dict[str, Any]) -> tuple[float, float] | None:
        details = ride.get("details") or {}
        info = (ride.get("list_row") or {}).get("rideInfo") or {}
        stop = str(info.get("passengerStationName") or "")
        member_id = self.member_id()
        for station in details.get("stations") or []:
            if not isinstance(station, dict):
                continue
            if not is_your_station(station, stop, member_id):
                continue
            try:
                return float(station.get("lat")), float(station.get("lng"))
            except (TypeError, ValueError):
                return None
        return None

    def _register_devices(self) -> None:
        registry = dr.async_get(self.hass)
        hub_id = self.hub_id
        customer = (self.store.user or {}).get("customer") or {}
        person = (self.store.user or {}).get("person") or {}
        name = customer.get("name") or person.get("firstName") or "Traffical"
        registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, hub_id)},
            manufacturer=MANUFACTURER,
            name=f"Traffical · {name}",
            model="Account",
        )
        for key, ride in (self.data.get("rides") or {}).items():
            slug = ride.get("name") or key
            registry.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, f"{hub_id}:{key}")},
                via_device=(DOMAIN, hub_id),
                manufacturer=MANUFACTURER,
                name=str(slug),
                model="Ride",
            )

    @callback
    def hub_device_info(self) -> dict[str, Any]:
        customer = (self.store.user or {}).get("customer") or {}
        person = (self.store.user or {}).get("person") or {}
        name = customer.get("name") or person.get("firstName") or "Traffical"
        return {
            "identifiers": {(DOMAIN, self.hub_id)},
            "manufacturer": MANUFACTURER,
            "name": f"Traffical · {name}",
            "model": "Account",
        }

    @callback
    def ride_device_info(self, key: str) -> dict[str, Any]:
        ride = self.ride(key)
        slug = ride.get("name") or key
        return {
            "identifiers": {(DOMAIN, f"{self.hub_id}:{key}")},
            "via_device": (DOMAIN, self.hub_id),
            "manufacturer": MANUFACTURER,
            "name": str(slug),
            "model": "Ride",
        }

    async def async_switch_child(self, child_id: str) -> None:
        refresh = self.store.tokens.get("refresh_token")
        if not refresh:
            raise ConfigEntryAuthFailed("no refresh token")
        body = await self.identity.switch_child(child_id, refresh)
        self.store.set_tokens(body)
        self.store.data["child_id"] = child_id
        self._persist_entry()
        await self.async_request_refresh()

    async def async_check_in(self, key: str, check_in: bool) -> None:
        ride = self.ride(key)
        ride_id = ride.get("ride_id")
        member_id = self.member_id()
        if ride_id is None or member_id is None:
            return
        await self.mobile.check_in_passenger(int(ride_id), member_id, check_in)
        await self.async_request_refresh()

    async def async_not_coming(self, key: str) -> None:
        ride = self.ride(key)
        route_id = ride.get("route_id")
        member_id = self.member_id()
        if route_id is None or member_id is None:
            return
        await self.mobile.remove_passenger(
            int(route_id), member_id, date.today().isoformat()
        )
        await self.async_request_refresh()


async def async_create_coordinator(
    hass: HomeAssistant, entry: ConfigEntry
) -> TrafficalCoordinator:
    store = SessionStore()
    store.load_from_mapping(dict(entry.data))
    session = client_session()
    identity = IdentityClient(
        store.identity_url,
        session,
        language=store.language,
        tokens_provider=lambda: store.tokens,
    )
    mobile = MobileClient(
        store.api_url,
        session,
        language=store.language,
        tokens_provider=lambda: store.tokens,
    )
    hubs = SignalRHubs(session, store.api_url, lambda: store.tokens)
    return TrafficalCoordinator(hass, entry, store, identity, mobile, hubs, session)
