#!/usr/bin/env python3
"""Console login client for Traffical / Shift identity.

HA-free code lives in custom_components/traffical/{managers,models,common}/.
Session is stored in data/config.json at the repo root.

Usage:
  python engine/entrypoint.py
  python -m engine.entrypoint
  python engine/entrypoint.py --clean
  python engine/entrypoint.py --env Live
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
import logging
import os
import sys
from typing import Any

import ha_free_path  # noqa: F401  # must precede traffical imports
from traffical.common.consts import (
    CONFIG_PATH,
    DEFAULT_ENVIRONMENT,
    ENVIRONMENTS,
)
from traffical.common.helpers import client_session, create_pkce
from traffical.managers.identity_client import IdentityClient
from traffical.managers.mobile_client import MobileClient
from traffical.managers.signalr_client import SignalRHubs
from traffical.managers.store import SessionStore
from traffical.models.exceptions import ApiError
from traffical.models.rides import (
    is_your_station,
    list_row_ids,
    rides_customer_type,
    status_finished,
    status_live,
)

_LOGGER = logging.getLogger(__name__)

AUTO_TRACK_INTERVAL_S = 30.0


def _configure_logging() -> None:
    raw = (os.environ.get("TRAFFICAL_LOG_LEVEL") or "").strip().upper()
    if raw:
        level = getattr(logging, raw, logging.INFO)
    else:
        debug = str(os.environ.get("DEBUG", "")).lower() == "true"
        level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(threadName)s[%(thread)d] %(levelname)s %(name)s %(message)s"
        )
    )
    root.addHandler(handler)
    for name in ("aiohttp", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def prompt(message: str) -> str:
    try:
        return input(message).strip()
    except EOFError:
        raise SystemExit("No input.") from None


class App:
    def __init__(
        self,
        store: SessionStore,
        identity: IdentityClient,
        mobile: MobileClient,
        hubs: SignalRHubs,
    ) -> None:
        self.store = store
        self.identity = identity
        self.mobile = mobile
        self.hubs = hubs
        self.day_date: str | None = None
        self.day_rides: list[dict[str, Any]] = []
        self.auto_track = False
        self._lock = asyncio.Lock()
        self._auto_stop = asyncio.Event()
        self._auto_task: asyncio.Task[None] | None = None
        self.mobile.on_unauthorized = self._try_refresh
        self.identity.on_unauthorized = self._try_refresh

    async def run(self, clean: bool = False, env: str | None = None) -> int:
        if clean:
            if self.store.clear():
                _LOGGER.info(f"Removed session file {CONFIG_PATH}")
            else:
                _LOGGER.info("No saved session to clear")

        self.store.load()
        if not self.store.identity_url:
            self.store.apply_environment(env or DEFAULT_ENVIRONMENT)
            self.store.save()
        elif env and env != self.store.environment:
            _LOGGER.warning(
                f"Saved session is {self.store.environment}. Use --clean to switch to {env}."
            )

        self.identity.base_url = self.store.identity_url.rstrip("/")
        self.identity.language = self.store.language
        self.mobile.base_url = self.store.api_url.rstrip("/")
        self.mobile.language = self.store.language
        self.hubs.api_url = self.store.api_url.rstrip("/")

        if await self._resume_logged_in():
            return await self._passenger_menu()

        if self.store.phone:
            _LOGGER.info("Saved phone; skipping to OTP")
            await self._otp_step(request_if_missing=True)
            return await self._passenger_menu()

        self._collect_phone()
        await self._request_otp()
        await self._otp_step(request_if_missing=False)
        return await self._passenger_menu()

    def _log_logged_in(self) -> None:
        user = self.store.user
        person = user.get("person") or {}
        _LOGGER.info(
            f"login ok environment={self.store.environment} "
            f"role={person.get('role')} memberId={person.get('memberId')} "
            f"session={CONFIG_PATH}"
        )

    async def _request_otp(self) -> None:
        try:
            ticket, expired_in = await self.identity.request_otp(
                self.store.phone, self.store.app_hash
            )
        except ApiError as exc:
            _LOGGER.error(f"{exc}")
            raise SystemExit(str(exc)) from exc
        self.store.set_otp(ticket, expired_in)
        self.store.save()
        _LOGGER.info("otp requested")
        if expired_in is not None:
            _LOGGER.debug(f"OTP expiredIn={expired_in} seconds")

    async def _try_refresh(self) -> bool:
        async with self._lock:
            refresh = self.store.tokens.get("refresh_token")
            if not refresh:
                return False
            try:
                body = await self.identity.refresh(refresh)
            except ApiError as exc:
                _LOGGER.error(f"Refresh failed: {exc}")
                return False
            self.store.set_tokens(body)
            self.store.save()
            _LOGGER.info("Access token refreshed")
            return True

    async def _resume_logged_in(self) -> bool:
        if not self.store.tokens.get("access_token"):
            return False

        try:
            user = await self.identity.userinfo()
        except PermissionError:
            _LOGGER.warning("Access token rejected; trying refresh")
            if not await self._try_refresh():
                self.store.clear_tokens()
                self.store.save()
                return False
            try:
                user = await self.identity.userinfo()
            except (PermissionError, ApiError) as exc:
                _LOGGER.error(f"Still not authenticated: {exc}")
                self.store.clear_tokens()
                self.store.save()
                return False
        except ApiError as exc:
            _LOGGER.error(f"userinfo failed: {exc}")
            return False

        self.store.set_user(user)
        self.store.save()
        self._log_logged_in()
        return True

    def _collect_phone(self) -> None:
        phone = prompt("Phone number: ")
        if not phone:
            _LOGGER.error("Phone is required.")
            raise SystemExit("Phone is required.")
        self.store.phone = phone
        self.store.save()

    async def _otp_step(self, request_if_missing: bool) -> None:
        if request_if_missing and not self.store.otp_ticket:
            await self._request_otp()

        print(f"OTP for {self.store.phone}")
        print("Enter the code, or type 'r' to request a new OTP.")
        otp = prompt("OTP: ")
        if otp.lower() == "r":
            await self._request_otp()
            otp = prompt("OTP: ")
        if not otp or otp.lower() == "r":
            _LOGGER.error("OTP is required.")
            raise SystemExit("OTP is required.")

        verifier, challenge = create_pkce()
        try:
            code = await self.identity.authorize(
                self.store.phone,
                otp,
                self.store.otp_ticket,
                challenge,
                self.store.device_id,
            )
        except ApiError as exc:
            _LOGGER.warning(f"Authorize failed: {exc}")
            _LOGGER.info("Requesting a new OTP")
            await self._request_otp()
            otp = prompt("OTP: ")
            if not otp:
                _LOGGER.error("OTP is required.")
                raise SystemExit("OTP is required.")
            verifier, challenge = create_pkce()
            code = await self.identity.authorize(
                self.store.phone,
                otp,
                self.store.otp_ticket,
                challenge,
                self.store.device_id,
            )

        token_body = await self.identity.exchange_code(
            code, verifier, retry_redirect=True
        )
        self.store.set_tokens(token_body)
        self.store.clear_otp()
        self.store.save()

        user = await self.identity.userinfo()
        self.store.set_user(user)
        self.store.save()
        self._log_logged_in()

    def _policy_flag(self, policies: dict, group: str, key: str = "isActive") -> Any:
        block = policies.get(group) or {}
        if isinstance(block, dict):
            return block.get(key)
        return None

    async def _load_passenger_context(self) -> None:
        try:
            roles = await self.mobile.user_roles()
            self.store.set_roles(roles)
            self.store.save()
            _LOGGER.info(
                f"Loaded {len(roles) if isinstance(roles, list) else 1} role group(s)"
            )
        except (ApiError, Exception) as exc:
            _LOGGER.error(f"User/Roles failed: {exc}")

        try:
            policies = await self.mobile.passenger_policies()
        except (ApiError, Exception) as exc:
            _LOGGER.error(f"Passenger policies failed: {exc}")
            return
        if not isinstance(policies, dict):
            policies = {}
        self.store.set_policies(policies)
        self.store.save()
        _LOGGER.info(
            f"PassengerPolicy isReservationEnabled={policies.get('isReservationEnabled')} "
            f"gotOnRideReport.isActive={self._policy_flag(policies, 'gotOnRideReport')} "
            f"notComingReport.isActive={self._policy_flag(policies, 'notComingReport')}"
        )

    def _customer_type_path(self) -> str:
        customer = (self.store.user or {}).get("customer") or {}
        return rides_customer_type(customer.get("type"))

    def _person_name(self, block: Any) -> str:
        if not isinstance(block, dict):
            return ""
        return " ".join(p for p in (block.get("firstName"), block.get("lastName")) if p)

    def _session_banner(self) -> None:
        user = self.store.user or {}
        person = user.get("person") or {}
        parent = user.get("parent") or {}
        passenger = self._person_name(person) or "passenger"
        parent_name = self._person_name(parent)
        if parent_name:
            print(f"Logged in as {parent_name} (parent) · passenger {passenger}")
        else:
            print(f"Logged in as {passenger}")

    def _clock(self, value: Any) -> str:
        if not value or not isinstance(value, str):
            return ""
        text = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return value[11:16] if len(value) >= 16 else value
        return dt.strftime("%H:%M")

    def _driver_name(self, details: dict[str, Any], info: dict[str, Any]) -> str:
        driver = details.get("driver")
        if isinstance(driver, dict):
            name = (driver.get("name") or "").strip()
            if name:
                return name
        return (info.get("driver") or "").strip()

    def _checkin_label(self, check: Any) -> str:
        if not isinstance(check, dict):
            return "—"
        return "yes" if check.get("checkIn") else "no"

    def _member_id(self) -> int | None:
        person = (self.store.user or {}).get("person") or {}
        try:
            return int(person.get("memberId"))
        except (TypeError, ValueError):
            return None

    def _station_label(self, station: dict[str, Any]) -> str:
        name = (station.get("name") or station.get("stationName") or "").strip()
        address = str(station.get("address") or "").strip()
        if station.get("isTarget"):
            return name or address
        return address or name

    def _view_suffix(self, status: str) -> str:
        if status_live(status):
            return "live"
        if status_finished(status):
            return "finished, no live GPS"
        return "GPS starts when ongoing"

    async def _load_day(self, date_str: str) -> None:
        customer_type = self._customer_type_path()
        try:
            rides = await self.mobile.list_rides(customer_type, date_str)
        except (ApiError, Exception) as exc:
            _LOGGER.error(f"List rides failed: {exc}")
            async with self._lock:
                self.day_date = date_str
                self.day_rides = []
            return
        if not isinstance(rides, list):
            rides = []
        ride_ids: list[int] = []
        for ride in rides:
            _ticket, ride_id = list_row_ids(ride)
            if ride_id is not None:
                ride_ids.append(ride_id)
        statuses: dict[int, dict] = {}
        if ride_ids:
            try:
                raw = await self.mobile.checkin_statuses(ride_ids)
                if isinstance(raw, list):
                    for item in raw:
                        rid = item.get("rideId")
                        if rid is not None:
                            try:
                                statuses[int(rid)] = item
                            except (TypeError, ValueError):
                                pass
            except (ApiError, Exception) as exc:
                _LOGGER.error(f"Check-in statuses failed: {exc}")
        _LOGGER.info(f"{len(rides)} ride(s) for {date_str} ({customer_type})")
        built: list[dict[str, Any]] = []
        for i, ride in enumerate(rides, start=1):
            info = (
                ride.get("rideInfo") if isinstance(ride.get("rideInfo"), dict) else {}
            )
            ticket = str(info.get("rideTicket") or ride.get("rideTicket") or "")
            ride_id_raw = info.get("rideId") or ride.get("rideId")
            try:
                ride_id = int(ride_id_raw) if ride_id_raw is not None else None
            except (TypeError, ValueError):
                ride_id = None
            details: dict[str, Any] = {}
            if ticket:
                try:
                    loaded = await self.mobile.ride_details(ticket)
                    if isinstance(loaded, dict):
                        details = loaded
                        if ride_id is None:
                            try:
                                ride_id = int(details.get("rideId"))
                            except (TypeError, ValueError):
                                ride_id = None
                except (ApiError, Exception) as exc:
                    _LOGGER.error(f"Ride details failed for ride {i}: {exc}")
            status = str(details.get("status") or ride.get("status") or "")
            check = statuses.get(ride_id) if ride_id is not None else None
            built.append(
                {
                    "index": i,
                    "list_row": ride,
                    "details": details,
                    "ticket": ticket,
                    "ride_id": ride_id,
                    "status": status,
                    "checkin": check,
                }
            )
        async with self._lock:
            self.day_date = date_str
            self.day_rides = built

    def _print_day_dump(self) -> None:
        print(f"Date {self.day_date} · {len(self.day_rides)} ride(s)")
        if not self.day_rides:
            print("No rides for that date.")
            return
        member_id = self._member_id()
        for item in self.day_rides:
            self._print_day_ride(item, member_id)

    def _print_day_ride(self, item: dict[str, Any], member_id: int | None) -> None:
        ride = item.get("list_row") or {}
        info = ride.get("rideInfo") if isinstance(ride.get("rideInfo"), dict) else {}
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        name = details.get("name") or ride.get("name") or ride.get("number") or ""
        start = self._clock(details.get("startTime") or info.get("startDateTime"))
        end = self._clock(details.get("endTime") or info.get("endDateTime"))
        status = item.get("status") or ""
        check_s = self._checkin_label(item.get("checkin"))
        passenger_stop = str(info.get("passengerStationName") or "")
        stations = (
            details.get("stations") if isinstance(details.get("stations"), list) else []
        )
        print()
        print(f"── Ride {item.get('index')}  {name}")
        print(f"    {start}–{end}  {status}  check-in: {check_s}")
        driver = self._driver_name(details, info) or "—"
        shuttle = details.get("shuttleCompanyName") or info.get("shuttleCompany") or "—"
        print(f"    Driver {driver}  ·  {shuttle}")
        if passenger_stop:
            print(f"    Your stop: {passenger_stop}")
        if not stations:
            return
        print("    Stations:")
        for station in stations:
            if not isinstance(station, dict):
                continue
            marks = []
            if is_your_station(station, passenger_stop, member_id):
                marks.append("← you")
            if station.get("isTarget"):
                marks.append("(destination)")
            extra = ("  " + " ".join(marks)) if marks else ""
            print(f"      {self._station_label(station)}{extra}")

    def _build_menu(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if self.hubs.track_ride_id is not None:
            items.append({"label": "Stop live GPS", "action": "stop"})
        for ride in self.day_rides:
            idx = ride.get("index")
            suffix = self._view_suffix(str(ride.get("status") or ""))
            items.append(
                {
                    "label": f"Ride {idx} — view path ({suffix})",
                    "action": "view",
                    "ride": ride,
                }
            )
        if self.auto_track:
            items.append({"label": "Auto-track changes (on)", "action": "auto"})
        else:
            items.append({"label": "Auto-track changes (off)", "action": "auto"})
        items.append({"label": "Change date", "action": "date"})
        items.append({"label": "Quit", "action": "quit"})
        return items

    def _print_menu(self, items: list[dict[str, Any]]) -> None:
        print()
        print("Menu")
        for i, item in enumerate(items, start=1):
            print(f"  {i}. {item['label']}")
        print()

    async def _change_date(self) -> None:
        raw = prompt("Date [YYYY-MM-DD]: ")
        if not raw:
            print("Date unchanged.")
            return
        try:
            date.fromisoformat(raw)
        except ValueError:
            print("Use YYYY-MM-DD.")
            return
        await self.hubs.stop_track()
        await self._load_day(raw)
        self._print_day_dump()

    def _print_path_snapshot(self, path: Any) -> None:
        if not path:
            print("No monitoring path yet (ride may not be live).")
            return
        points = path if isinstance(path, list) else [path]
        print(f"Monitoring path points: {len(points)}")
        for point in points[-5:]:
            if isinstance(point, dict):
                when = (
                    point.get("dateTime") or point.get("createdAt") or point.get("time")
                )
                print(f"  {when}")
            else:
                print(f"  {point}")

    async def _print_track_event(self, event: str, payload: Any) -> None:
        if event == "ArrivedToStation":
            station_id = (
                payload.get("stationId") if isinstance(payload, dict) else payload
            )
            print(f"[track] ArrivedToStation stationId={station_id}")
            return
        print(f"[track] {event}")

    def _resolved_from_day(
        self, ride: dict[str, Any]
    ) -> tuple[int, dict[str, Any]] | None:
        details = ride.get("details") if isinstance(ride.get("details"), dict) else {}
        ride_id = ride.get("ride_id")
        if ride_id is None:
            return None
        try:
            return int(ride_id), details
        except (TypeError, ValueError):
            return None

    async def _cmd_track(self, ride: dict[str, Any]) -> None:
        async with self._lock:
            await self._cmd_track_locked(ride)

    async def _cmd_track_locked(self, ride: dict[str, Any]) -> None:
        resolved = self._resolved_from_day(ride)
        if resolved is None:
            return
        ride_id, details = resolved
        status = str(ride.get("status") or details.get("status") or "")
        try:
            path = await self.mobile.monitoring_path(ride_id)
        except (ApiError, Exception) as exc:
            _LOGGER.error(f"Monitoring path failed: {exc}")
            path = []
        self._print_path_snapshot(path)
        if status_live(status):
            try:
                await self.hubs.start_track(ride_id, self._print_track_event)
                print(
                    "Listening for live coordinates. Stop will appear in the next menu."
                )
            except Exception as exc:
                _LOGGER.error(f"Dashboard hub failed: {exc}")
            return
        if status_finished(status):
            print(
                f"Ride status is {status}; live GPS has ended. Showing path snapshot only."
            )
            return
        print(
            f"Ride status is {status or 'unknown'}; live GPS starts when the ride is ongoing."
        )

    async def _cmd_stop(self) -> None:
        await self.hubs.stop_track()
        print("Stopped live GPS.")

    def _match_day_ride(
        self, ticket: str, ride_id: int | None
    ) -> dict[str, Any] | None:
        for ride in self.day_rides:
            if ticket and ride.get("ticket") and ticket == ride.get("ticket"):
                return ride
            cached_id = ride.get("ride_id")
            if (
                ride_id is not None
                and cached_id is not None
                and int(cached_id) == ride_id
            ):
                return ride
        return None

    def _checkin_flag(self, check: Any) -> bool | None:
        if not isinstance(check, dict):
            return None
        return bool(check.get("checkIn"))

    async def _toggle_auto_track(self) -> None:
        if self.auto_track:
            await self._stop_auto_track_poller()
            self.auto_track = False
            print("Auto-track off.")
            return
        self.auto_track = True
        self._start_auto_track_poller()
        print(f"Auto-track on (every {int(AUTO_TRACK_INTERVAL_S)}s).")

    def _start_auto_track_poller(self) -> None:
        if self._auto_task is not None and not self._auto_task.done():
            return
        self._auto_stop.clear()
        self._auto_task = asyncio.create_task(self._auto_track_loop(), name="AutoTrack")

    async def _stop_auto_track_poller(self) -> None:
        self._auto_stop.set()
        task = self._auto_task
        self._auto_task = None
        if task is not None and not task.done():
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)

    async def _shutdown_passenger(self) -> None:
        self.auto_track = False
        await self._stop_auto_track_poller()
        await self.hubs.stop_track()

    async def _auto_track_loop(self) -> None:
        while not self._auto_stop.is_set():
            try:
                await self._auto_track_tick()
            except Exception as exc:
                _LOGGER.error(f"Auto-track poll failed: {exc}")
            try:
                await asyncio.wait_for(self._auto_stop.wait(), AUTO_TRACK_INTERVAL_S)
            except asyncio.TimeoutError:
                continue

    async def _auto_track_tick(self) -> None:
        date_str = self.day_date
        if not date_str or not self.auto_track:
            return
        customer_type = self._customer_type_path()
        try:
            rides = await self.mobile.list_rides(customer_type, date_str)
        except ApiError as exc:
            if exc.status_code == 401:
                print("Session expired. Auto-track off. Quit and log in again.")
                if self.auto_track:
                    await self._toggle_auto_track()
                return
            _LOGGER.error(f"Auto-track list failed: {exc}")
            return
        except Exception as exc:
            _LOGGER.error(f"Auto-track list failed: {exc}")
            return
        if not isinstance(rides, list):
            rides = []
        ride_ids: list[int] = []
        for row in rides:
            _ticket, ride_id = list_row_ids(row)
            if ride_id is not None:
                ride_ids.append(ride_id)
        statuses: dict[int, dict] = {}
        if ride_ids:
            try:
                raw = await self.mobile.checkin_statuses(ride_ids)
                if isinstance(raw, list):
                    for item in raw:
                        rid = item.get("rideId")
                        if rid is not None:
                            try:
                                statuses[int(rid)] = item
                            except (TypeError, ValueError):
                                pass
            except (ApiError, Exception) as exc:
                _LOGGER.error(f"Auto-track check-in failed: {exc}")
        start_view: dict[str, Any] | None = None
        async with self._lock:
            for row in rides:
                ticket, ride_id = list_row_ids(row)
                cached = self._match_day_ride(ticket, ride_id)
                if cached is None:
                    continue
                new_status = str(row.get("status") or "")
                old_status = str(cached.get("status") or "")
                if new_status and new_status != old_status:
                    print(
                        f"[auto] Ride {cached.get('index')} {old_status} → {new_status}"
                    )
                    cached["status"] = new_status
                    cached["list_row"] = row
                    details = cached.get("details")
                    if isinstance(details, dict):
                        details["status"] = new_status
                    if status_live(new_status) and not status_live(old_status):
                        if self.hubs.track_ride_id is None and start_view is None:
                            start_view = cached
                    if status_finished(
                        new_status
                    ) and self.hubs.track_ride_id == cached.get("ride_id"):
                        await self.hubs.stop_track()
                        print(
                            f"[auto] Ride {cached.get('index')} live GPS ended (finished)."
                        )
                check = (
                    statuses.get(cached["ride_id"])
                    if cached.get("ride_id") is not None
                    else None
                )
                old_flag = self._checkin_flag(cached.get("checkin"))
                new_flag = self._checkin_flag(check)
                if check is not None and new_flag is not None and new_flag != old_flag:
                    print(
                        f"[auto] Ride {cached.get('index')} check-in: "
                        f"{'yes' if old_flag else 'no'} → {'yes' if new_flag else 'no'}"
                    )
                    cached["checkin"] = check
            if start_view is not None:
                print(f"[auto] Ride {start_view.get('index')} is live; starting GPS.")
                await self._cmd_track_locked(start_view)

    async def _passenger_menu(self) -> int:
        await self._load_passenger_context()
        self._session_banner()
        await self._load_day(date.today().isoformat())
        self._print_day_dump()
        while True:
            items = self._build_menu()
            self._print_menu(items)
            try:
                line = prompt("> ")
            except SystemExit:
                await self._shutdown_passenger()
                return 0
            if not line:
                print("Enter a menu number.")
                continue
            try:
                choice = int(line)
            except ValueError:
                print("Enter a menu number.")
                continue
            if choice < 1 or choice > len(items):
                print("Enter a menu number.")
                continue
            picked = items[choice - 1]
            action = picked["action"]
            if action == "quit":
                await self._shutdown_passenger()
                return 0
            if action == "stop":
                await self._cmd_stop()
                continue
            if action == "view":
                await self._cmd_track(picked["ride"])
                continue
            if action == "date":
                await self._change_date()
                continue
            if action == "auto":
                await self._toggle_auto_track()
                continue
            print("Enter a menu number.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Traffical / Shift console login")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete data/config.json and start from the phone prompt",
    )
    parser.add_argument(
        "--env",
        choices=list(ENVIRONMENTS),
        help="Environment for a new session (default: Live). Ignored if a session already exists unless --clean.",
    )
    return parser.parse_args()


async def async_main() -> int:
    _configure_logging()
    args = parse_args()
    store = SessionStore()
    session = client_session()
    try:
        identity = IdentityClient(
            base_url="",
            session=session,
            tokens_provider=lambda: store.tokens,
        )
        mobile = MobileClient(
            base_url="",
            session=session,
            tokens_provider=lambda: store.tokens,
        )
        hubs = SignalRHubs(session, "", lambda: store.tokens)
        return await App(store, identity, mobile, hubs).run(
            clean=args.clean, env=args.env
        )
    finally:
        await session.close()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
