"""Traffical data coordinator — HTTP poll + auto SignalR."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
import logging
import math
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
from ..models.coordinates import MonitoredPath, coord_from_payload
from ..models.entity_specs import policy_active
from ..models.entity_values import EntityContext
from ..models.exceptions import ApiError, AuthError
from ..models.ride_window import RideWindow
from ..models.rides import (
    Ride,
    rides_customer_type,
    status_finished,
    status_live,
)
from ..models.stations import station_event_id
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
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.entry = entry
        self.store = store
        self.identity = identity
        self.mobile = mobile
        self.hubs = hubs
        self._session = session
        self._stopping = False
        self._reauth_started = False
        self._entity_listeners: list[Callable[[], None]] = []
        self._route_refresh_task: asyncio.Task[None] | None = None
        self.window = RideWindow()
        self.data: dict[str, Any] = {
            "rides": {},
            "user": {},
            "policies": {},
            "children": [],
            "session_ok": False,
            "live_key": None,
            "focus_ride_key": None,
            "focus": None,
            "occurrences": [],
            "loaded_dates": [],
        }
        self._force_dates: set[str] = set()
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
        return policy_active(self.data.get("policies"), group)

    async def async_start(self) -> None:
        _LOGGER.info("coordinator starting")
        await self.async_config_entry_first_refresh()
        if not self._stopping:
            await self.hubs.start_mobile(self._on_mobile_hub_event)
        self._register_devices()

    async def async_stop(self) -> None:
        self._stopping = True
        _LOGGER.info("coordinator stopping")
        if self._route_refresh_task is not None:
            self._route_refresh_task.cancel()
            self._route_refresh_task = None
        await self.async_shutdown()
        await self.hubs.stop_mobile()
        await self.hubs.stop_track()
        await self._session.close()

    def register_entity_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Subscribe a platform to structural (ride / station) changes."""
        self._entity_listeners.append(listener)

        def _unsub() -> None:
            if listener in self._entity_listeners:
                self._entity_listeners.remove(listener)

        return _unsub

    def _notify_entities(self) -> None:
        for listener in list(self._entity_listeners):
            listener()

    @callback
    def entity_context(self) -> EntityContext:
        """Account-level snapshot every entity resolves against."""
        data = self.data or {}
        person = (self.store.user or {}).get("person") or {}
        name = " ".join(
            part for part in (person.get("firstName"), person.get("lastName")) if part
        )
        return EntityContext(
            member_id=self.member_id(),
            session_ok=bool(data.get("session_ok")),
            children=tuple(data.get("children") or ()),
            policies=data.get("policies") or {},
            focus=data.get("focus"),
            focus_ride_key=data.get("focus_ride_key"),
            passenger_name=name,
        )

    @callback
    def entity_caps(self) -> dict[str, Any]:
        """Tenant capabilities that gate which entities exist at all."""
        data = self.data or {}
        return {
            "policies": data.get("policies") or {},
            "children": tuple(data.get("children") or ()),
        }

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
        if not self._stopping:
            await self.hubs.restart()
        return True

    def _persist_entry(self) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, **self.store.persist_fields()}
        )

    async def _start_reauth(self) -> None:
        if self._reauth_started:
            return
        self._reauth_started = True
        _LOGGER.error(
            f"starting reauth flow entry_id={partial_id(self.entry.entry_id)}"
        )
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
        force = set(self._force_dates)
        self._force_dates.clear()
        previous = {key: dict(ride) for key, ride in (self.window.rides or {}).items()}
        await self._fill_window(customer_type, date.today(), force)
        rides = self.window.bind()
        self._emit_ride_changes(previous, rides)
        focus = self.window.focus
        _LOGGER.info(
            f"ride list refreshed count={sum(1 for r in rides.values() if r.get('assigned_today'))}"
        )
        self._adjust_interval(focus)
        live_key = self.window.live_key
        data = {
            "rides": rides,
            "occurrences": self.window.occurrences,
            "loaded_dates": sorted(self.window.loaded_dates),
            "user": self.store.user,
            "policies": policies,
            "children": children,
            "session_ok": True,
            "live_key": live_key,
            "focus": focus,
            "focus_ride_key": self.window.map_focus_key,
        }
        self.data = data
        self._register_devices()
        await self._sync_signalr(live_key, rides)
        self._notify_entities()
        return data

    async def _fill_window(
        self, customer_type: str, today: date, force_dates: set[str]
    ) -> None:
        """List today, then lookahead days only until a next ride shows up."""
        self.window.start_day(today)
        listed: set[str] = set()
        if self.window.needs_today(force_dates):
            await self._list_day(customer_type, today, listed)
        while self.window.focus is None:
            day = self.window.next_missing_date()
            if day is None:
                break
            await self._list_day(customer_type, day, listed)
        for day in self.window.forced_days(force_dates):
            await self._list_day(customer_type, day, listed)

    async def _list_day(self, customer_type: str, day: date, listed: set[str]) -> None:
        service_date = day.isoformat()
        if service_date in listed:
            return
        rows = await self.mobile.list_rides(customer_type, service_date)
        if not isinstance(rows, list):
            rows = []
        ride_ids = [
            ride_id
            for ride_id in (Ride(row).ride_id for row in rows)
            if ride_id is not None
        ]
        statuses = await self._checkin_map(ride_ids)
        entries: list[tuple[Any, dict[str, Any], Any]] = []
        for row in rows:
            ride = Ride(row)
            details: dict[str, Any] = {}
            if ride.ticket:
                loaded = await self.mobile.ride_details(ride.ticket)
                if isinstance(loaded, dict):
                    details = loaded
            check = statuses.get(ride.ride_id) if ride.ride_id is not None else None
            entries.append((row, details, check))
        self.window.set_day(service_date, entries)
        listed.add(service_date)

    async def _checkin_map(self, ride_ids: list[int]) -> dict[int, dict[str, Any]]:
        statuses: dict[int, dict[str, Any]] = {}
        if not ride_ids:
            return statuses
        raw_status = await self.mobile.checkin_statuses(ride_ids)
        if not isinstance(raw_status, list):
            return statuses
        for item in raw_status:
            if not isinstance(item, dict):
                continue
            try:
                statuses[int(item.get("rideId"))] = item
            except (TypeError, ValueError):
                pass
        return statuses

    def _emit_ride_changes(
        self,
        previous: dict[str, dict[str, Any]],
        rides: dict[str, dict[str, Any]],
    ) -> None:
        for key, ride in rides.items():
            if not ride.get("assigned_today"):
                continue
            old = previous.get(key) or {}
            self._emit_status(
                key,
                str(old.get("status") or ""),
                str(ride.get("status") or ""),
                ride.get("ride_id"),
                ride.get("details") or {},
                ride.get("list_row") or {},
            )
            self._emit_checkin(
                key, old.get("checkin"), ride.get("checkin"), ride.get("ride_id")
            )

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
        ride = Ride(row, details)
        self.hass.bus.async_fire(
            EVENT_RIDE_STATUS_CHANGED,
            {
                "ride_id": ride_id,
                "old": old_status,
                "new": new_status,
                "direction": ride.direction,
                "key": key,
            },
        )
        if status_live(new_status) and not status_live(old_status):
            self.hass.bus.async_fire(
                EVENT_RIDE_STARTED,
                {"ride_id": ride_id, "name": ride.name, "key": key},
            )
        if status_finished(new_status) and not status_finished(old_status):
            self.hass.bus.async_fire(
                EVENT_RIDE_FINISHED,
                {"ride_id": ride_id, "checked_in": None, "key": key},
            )

    def _emit_checkin(self, key: str, old: Any, new: Any, ride_id: int | None) -> None:
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

    def _adjust_interval(self, focus: dict[str, Any] | None) -> None:
        now = datetime.now(timezone.utc)
        fast = False
        if focus:
            start = Ride.from_cache(focus).start
            if start and timedelta(0) <= (start - now) <= FAST_WINDOW:
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
        if self._stopping:
            return
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
        # Seed once before attaching; subsequent positions come from SignalR.
        try:
            path = await self.mobile.monitoring_path(int(ride_id))
        except ApiError as exc:
            _LOGGER.warning(f"monitoring path failed ride={partial_id(ride_id)}: {exc}")
            path = []
        moved = self._seed_path(live_key, path)
        _LOGGER.debug(
            f"position seed ride={partial_id(ride_id)} "
            f"points={len(MonitoredPath(path).points)} changed={moved}"
        )
        _LOGGER.debug(f"Monitor invoke rideId={ride_id}")
        await self.hubs.start_track(int(ride_id), self._on_hub_event)
        _LOGGER.info(f"SignalR connected rideId={ride_id}")

    async def _on_mobile_hub_event(self, event: str, payload: Any) -> None:
        if event == "UpdateRideStatus":
            await self._apply_streamed_status(payload)
            return
        if event == "RouteSuccessfulSave":
            self._schedule_route_refresh(payload)

    async def _apply_streamed_status(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        ride_id_raw = payload.get("Id")
        status_raw = payload.get("Status")
        try:
            ride_id = int(ride_id_raw)
        except (TypeError, ValueError):
            return
        if not isinstance(status_raw, str) or not status_raw:
            return
        applied = self.window.apply_status(ride_id, status_raw)
        if applied is None:
            _LOGGER.debug(
                f"status push ignored ride={partial_id(ride_id)} reason=not_cached"
            )
            return
        bound_key, old_status = applied
        rides = self.window.rides
        if bound_key is not None and old_status != status_raw:
            ride = rides.get(bound_key) or {}
            self._emit_status(
                bound_key,
                old_status,
                status_raw,
                ride_id,
                ride.get("details") or {},
                ride.get("list_row") or {},
            )
        live_key = self.window.live_key
        self.data["live_key"] = live_key
        self.data["focus"] = self.window.focus
        self.data["focus_ride_key"] = self.window.map_focus_key
        await self._sync_signalr(live_key, rides)
        self.async_set_updated_data(self.data)
        if status_finished(status_raw) and self.data.get("focus") is None:
            await self.async_request_refresh()

    def _schedule_route_refresh(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        start = parse_utc(payload.get("ChangeDateFrom"))
        end = parse_utc(payload.get("ChangeDateTo"))
        forced = self.window.overlapping_dates(
            start.date() if start else None,
            end.date() if end else None,
        )
        if not forced:
            return
        self._force_dates.update(forced)
        if self._route_refresh_task is not None:
            self._route_refresh_task.cancel()
        self._route_refresh_task = asyncio.create_task(
            self._debounced_route_refresh(), name="traffical-route-refresh"
        )

    async def _debounced_route_refresh(self) -> None:
        try:
            await asyncio.sleep(5)
            await self.async_request_refresh()
        except asyncio.CancelledError:
            raise
        finally:
            if self._route_refresh_task is asyncio.current_task():
                self._route_refresh_task = None

    def _seed_path(self, key: str, path: Any) -> bool:
        last = MonitoredPath(path).latest
        if last is None:
            return False
        lat, lng = coord_from_payload(last)
        ride = (self.data.get("rides") or {}).get(key)
        if ride is None or lat is None:
            return False
        if ride.get("lat") == lat and ride.get("lng") == lng:
            return False
        ride["lat"] = lat
        ride["lng"] = lng
        return True

    async def _on_hub_event(self, event: str, payload: Any) -> None:
        live_key = (self.data or {}).get("live_key")
        if not live_key:
            return
        rides = self.data.get("rides") or {}
        ride = rides.get(live_key)
        if ride is None:
            return
        if event == "ReceiveCoordinates":
            latest = MonitoredPath(payload).latest
            if latest is None:
                return
            lat, lng = coord_from_payload(latest)
            if lat is not None:
                ride["lat"] = lat
                ride["lng"] = lng
                self._maybe_approaching(live_key, ride)
                self.async_set_updated_data(self.data)
            return
        if event == "ArrivedToStation":
            sid = station_event_id(payload)
            if sid is not None:
                passed = set(ride.get("passed_stations") or [])
                passed.add(sid)
                ride["passed_stations"] = passed
            member_id = self.member_id()
            cached = Ride.from_cache(ride)
            is_mine = False
            for station in cached.stations:
                if str(station.station_id or "") == str(sid) and station.is_yours(
                    cached.passenger_stop, member_id
                ):
                    is_mine = True
                    break
            self.hass.bus.async_fire(
                EVENT_ARRIVED_STATION,
                {
                    "ride_id": ride.get("ride_id"),
                    "station_id": sid,
                    "is_my_station": is_mine,
                    "key": live_key,
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
            {
                "ride_id": ride.get("ride_id"),
                "distance_m": int(distance),
                "key": key,
            },
        )

    def _home_station(self, ride: dict[str, Any]) -> tuple[float, float] | None:
        station = Ride.from_cache(ride).your_station(self.member_id())
        if station is None or station.lat is None or station.lng is None:
            return None
        return station.lat, station.lng

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
        if not self._stopping:
            await self.hubs.restart()
        await self.async_request_refresh()

    async def async_action(self, action: str, ride_key: str | None = None) -> None:
        """Run a named catalog action (button presses)."""
        handlers: dict[str, Callable[[], Any]] = {
            "refresh": self.async_request_refresh,
            "check_in": lambda: self.async_check_in(str(ride_key), True),
            "check_out": lambda: self.async_check_in(str(ride_key), False),
            "not_coming": lambda: self.async_not_coming(str(ride_key)),
        }
        handler = handlers.get(action)
        if handler is None:
            _LOGGER.warning(f"unknown action {action}")
            return
        if action != "refresh" and ride_key is None:
            return
        await handler()

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
