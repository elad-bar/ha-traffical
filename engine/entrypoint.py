#!/usr/bin/env python3
"""Console login client for Traffical / Shift identity.

HA-free code lives in custom_components/traffical/{managers,models,common}/.
Session is stored in data/config.json at the repo root.

After login, prints loaded rides once and listens for HTTP polls
and SignalR until Ctrl+C.

Usage:
  python engine/entrypoint.py
  python -m engine.entrypoint
  python engine/entrypoint.py --clean
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv

try:
    from . import ha_free_path  # must precede traffical imports
except ImportError:  # run as a script, not as ``python -m engine.entrypoint``
    import ha_free_path  # must precede traffical imports

from traffical.common.consts import (
    CONFIG_PATH,
    FAST_WINDOW,
    POLL_INTERVAL,
    POLL_INTERVAL_FAST,
)
from traffical.common.helpers import client_session, create_pkce, partial_id
from traffical.managers.identity_client import IdentityClient
from traffical.managers.mobile_client import MobileClient
from traffical.managers.signalr_client import SignalRHubs
from traffical.managers.store import SessionStore
from traffical.models.coordinates import MonitoredPath, coord_from_payload
from traffical.models.exceptions import ApiError
from traffical.models.ride_window import RideWindow
from traffical.models.rides import (
    Ride,
    rides_customer_type,
    status_finished,
    status_live,
)
from traffical.models.stations import station_event_id

_LOGGER = logging.getLogger(__name__)

# Single knob for engine verbosity: a standard level name (DEBUG, INFO, …).
LOG_LEVEL_ENV = "LOG_LEVEL"


def _load_repo_dotenv(repo_root: str | os.PathLike[str] | None = None) -> bool:
    """Load repo-root ``.env`` without overriding variables already in the process."""
    root = Path(repo_root) if repo_root is not None else Path(ha_free_path.REPO_ROOT)
    return load_dotenv(root / ".env", override=False)


def _configure_logging() -> None:
    raw = (os.environ.get(LOG_LEVEL_ENV) or "").strip().upper()
    level = getattr(logging, raw, logging.INFO) if raw else logging.INFO
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


def format_point(point: Any) -> str:
    """Render a monitoring-path point as ``lat,lng`` with a timestamp if present.

    Falls back to the raw payload so an unexpected shape stays visible instead
    of printing an empty field.
    """
    lat, lng = coord_from_payload(point)
    if lat is None or lng is None:
        return repr(point)
    when = ""
    if isinstance(point, dict):
        for key in (
            "locatedAt",
            "LocatedAt",
            "dateTime",
            "DateTime",
            "createdAt",
            "time",
            "date",
            "Date",
        ):
            value = point.get(key)
            if value:
                when = f"  {value}"
                break
    return f"{lat:.6f},{lng:.6f}{when}"


async def prompt(message: str) -> str:
    """Read a line without blocking the event loop.

    ``input`` runs off-thread so OTP prompts do not block SignalR or token refresh.
    """
    try:
        line = await asyncio.to_thread(input, message)
    except EOFError:
        raise SystemExit("No input.") from None
    return line.strip()


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
        self.window = RideWindow()
        self._force_dates: set[str] = set()
        self._lock = asyncio.Lock()
        self._route_refresh_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self.mobile.on_unauthorized = self._try_refresh
        self.identity.on_unauthorized = self._try_refresh

    async def run(self, clean: bool = False) -> int:
        if clean:
            if self.store.clear():
                _LOGGER.info(f"Removed session file {CONFIG_PATH}")
            else:
                _LOGGER.info("No saved session to clear")

        self.store.load()
        if not self.store.identity_url:
            self.store.apply_live_hosts()
            self.store.save()

        self.identity.base_url = self.store.identity_url.rstrip("/")
        self.identity.language = self.store.language
        self.mobile.base_url = self.store.api_url.rstrip("/")
        self.mobile.language = self.store.language
        self.hubs.api_url = self.store.api_url.rstrip("/")

        if await self._resume_logged_in():
            return await self._passenger_listen()

        if self.store.phone:
            _LOGGER.info("Saved phone; skipping to OTP")
            await self._otp_step(request_if_missing=True)
            return await self._passenger_listen()

        await self._collect_phone()
        await self._request_otp()
        await self._otp_step(request_if_missing=False)
        return await self._passenger_listen()

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
            await self.hubs.restart()
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

    async def _collect_phone(self) -> None:
        phone = await prompt("Phone number: ")
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
        otp = await prompt("OTP: ")
        if otp.lower() == "r":
            await self._request_otp()
            otp = await prompt("OTP: ")
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
            otp = await prompt("OTP: ")
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

    async def _list_day(self, customer_type: str, day: date, listed: set[str]) -> None:
        service_date = day.isoformat()
        if service_date in listed:
            return
        try:
            rows = await self.mobile.list_rides(customer_type, service_date)
        except (ApiError, Exception) as exc:
            _LOGGER.error(f"List rides failed: {exc}")
            rows = []
        if not isinstance(rows, list):
            rows = []
        statuses = await self._checkin_map(rows)
        entries: list[tuple[Any, dict[str, Any], Any]] = []
        for row in rows:
            ride = Ride(row)
            details: dict[str, Any] = {}
            if ride.ticket:
                try:
                    loaded = await self.mobile.ride_details(ride.ticket)
                    if isinstance(loaded, dict):
                        details = loaded
                except (ApiError, Exception) as exc:
                    _LOGGER.error(f"Ride details failed: {exc}")
            check = statuses.get(ride.ride_id) if ride.ride_id is not None else None
            entries.append((row, details, check))
        self.window.set_day(service_date, entries)
        listed.add(service_date)

    async def _checkin_map(self, rows: list[Any]) -> dict[int, dict[str, Any]]:
        statuses: dict[int, dict[str, Any]] = {}
        ride_ids = [
            ride_id
            for ride_id in (Ride(row).ride_id for row in rows)
            if ride_id is not None
        ]
        if not ride_ids:
            return statuses
        try:
            raw = await self.mobile.checkin_statuses(ride_ids)
        except (ApiError, Exception) as exc:
            _LOGGER.error(f"Check-in statuses failed: {exc}")
            return statuses
        if not isinstance(raw, list):
            return statuses
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                statuses[int(item.get("rideId"))] = item
            except (TypeError, ValueError):
                pass
        return statuses

    async def _load_window(self) -> None:
        customer_type = self._customer_type_path()
        force = set(self._force_dates)
        self._force_dates.clear()
        today = date.today()
        self.window.start_day(today)
        listed: set[str] = set()
        if self.window.needs_today(force):
            await self._list_day(customer_type, today, listed)
        while self.window.focus is None:
            day = self.window.next_missing_date()
            if day is None:
                break
            await self._list_day(customer_type, day, listed)
        for day in self.window.forced_days(force):
            await self._list_day(customer_type, day, listed)
        self.window.bind()
        _LOGGER.info(
            f"{len(self.window.occurrences)} occurrence(s) "
            f"loaded_dates={sorted(self.window.loaded_dates)} ({customer_type})"
        )

    def _window_fingerprint(self) -> tuple[Any, ...]:
        occ = tuple(
            (
                item.get("ride_id"),
                item.get("service_date"),
                item.get("status"),
                (
                    (item.get("checkin") or {}).get("checkIn")
                    if isinstance(item.get("checkin"), dict)
                    else None
                ),
            )
            for item in self.window.occurrences
        )
        focus = self.window.focus
        return (occ, focus.get("ride_id") if focus else None, self.hubs.track_ride_id)

    def _poll_delay(self) -> float:
        now = datetime.now(timezone.utc)
        focus = self.window.focus
        if focus:
            start = Ride.from_cache(focus).start
            if start and timedelta(0) <= (start - now) <= FAST_WINDOW:
                return POLL_INTERVAL_FAST.total_seconds()
        return POLL_INTERVAL.total_seconds()

    def _print_window_dump(self) -> None:
        occurrences = self.window.occurrences
        print(
            f"Rides {self.window.today_iso} · {len(occurrences)} occurrence(s) "
            f"loaded={','.join(sorted(self.window.loaded_dates)) or 'none'}"
        )
        if not occurrences:
            print("No rides in the window.")
            return
        focus = self.window.focus
        focus_id = focus.get("ride_id") if focus else None
        by_date: dict[str, list[dict[str, Any]]] = {}
        for item in occurrences:
            by_date.setdefault(str(item.get("service_date") or ""), []).append(item)
        member_id = self._member_id()
        for date_str in sorted(by_date):
            print()
            print(f"Date {date_str} · {len(by_date[date_str])} ride(s)")
            for index, item in enumerate(by_date[date_str], start=1):
                shown = dict(item)
                shown["index"] = index
                mark = "  ← next" if shown.get("ride_id") == focus_id else ""
                self._print_day_ride(shown, member_id, mark)

    def _print_day_ride(
        self, item: dict[str, Any], member_id: int | None, mark: str = ""
    ) -> None:
        ride = Ride.from_cache(item)
        row = item.get("list_row") or {}
        info = row.get("rideInfo") if isinstance(row.get("rideInfo"), dict) else {}
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        check_s = self._checkin_label(item.get("checkin"))
        passenger_stop = ride.passenger_stop
        print()
        start = self._clock(details.get("startTime") or info.get("startDateTime"))
        end = self._clock(details.get("endTime") or info.get("endDateTime"))
        print(f"── Ride {item.get('index')}  {ride.name}{mark}")
        print(f"    {start}–{end}  {item.get('status') or ''}  check-in: {check_s}")
        driver = self._driver_name(details, info) or "—"
        shuttle = details.get("shuttleCompanyName") or info.get("shuttleCompany") or "—"
        print(f"    Driver {driver}  ·  {shuttle}")
        if passenger_stop:
            print(f"    Your stop: {passenger_stop}")
        stations = ride.stations
        if not stations:
            return
        print("    Stations:")
        for station in stations:
            marks = []
            if station.is_yours(passenger_stop, member_id):
                marks.append("← you")
            if station.is_target:
                marks.append("(destination)")
            extra = ("  " + " ".join(marks)) if marks else ""
            print(f"      {station.label}{extra}")

    def _print_path_snapshot(self, path: Any) -> None:
        points = MonitoredPath(path).points
        if not points:
            _LOGGER.debug("No monitoring path yet (ride may not be live).")
            return
        _LOGGER.debug(f"Monitoring path points: {len(points)}")
        for point in points[-5:]:
            _LOGGER.debug(f"  {format_point(point)}")

    async def _hub_event(self, event: str, payload: Any) -> None:
        if event == "ReceiveCoordinates":
            points = MonitoredPath(payload).points
            latest = points[-1] if points else None
            lat, lng = coord_from_payload(latest)
            if lat is None or lng is None:
                _LOGGER.warning("hub ReceiveCoordinates without usable coordinate")
                return
            _LOGGER.debug(
                f"hub ReceiveCoordinates source=hub count={len(points)} "
                f"point={lat:.6f},{lng:.6f}"
            )
            return
        if event == "ArrivedToStation":
            _LOGGER.info(f"hub ArrivedToStation station={station_event_id(payload)}")
            return
        _LOGGER.info(f"hub event target={event}")

    async def _mobile_hub_event(self, event: str, payload: Any) -> None:
        if event == "UpdateRideStatus":
            await self._apply_streamed_status(payload)
            return
        if event == "RouteSuccessfulSave":
            self._schedule_route_refresh(payload)

    async def _apply_streamed_status(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        try:
            ride_id = int(payload.get("Id"))
        except (TypeError, ValueError):
            return
        status = payload.get("Status")
        if not isinstance(status, str) or not status:
            return
        async with self._lock:
            applied = self.window.apply_status(ride_id, status)
            if applied is None:
                _LOGGER.debug(
                    f"status push ignored ride={partial_id(ride_id)} reason=not_cached"
                )
                return
            _, old_status = applied
            changed = old_status != status
            if changed:
                _LOGGER.info(
                    f"ride status changed ride={partial_id(ride_id)} "
                    f"old={old_status} new={status}"
                )
            await self._sync_live_track_locked()
        if not changed:
            return
        self._print_window_dump()
        if status_finished(status) and self.window.focus is None:
            await self._load_window()
            await self._sync_live_track()
            self._print_window_dump()

    def _schedule_route_refresh(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        try:
            start = datetime.fromisoformat(
                str(payload.get("ChangeDateFrom")).replace("Z", "+00:00")
            ).date()
            end = datetime.fromisoformat(
                str(payload.get("ChangeDateTo")).replace("Z", "+00:00")
            ).date()
        except (TypeError, ValueError):
            return
        forced = self.window.overlapping_dates(start, end)
        if not forced:
            return
        self._force_dates.update(forced)
        if self._route_refresh_task is not None:
            self._route_refresh_task.cancel()
        self._route_refresh_task = asyncio.create_task(
            self._debounced_route_refresh(), name="RouteRefresh"
        )

    async def _debounced_route_refresh(self) -> None:
        try:
            await asyncio.sleep(5)
            before = self._window_fingerprint()
            await self._load_window()
            await self._sync_live_track()
            _LOGGER.info("ride list refreshed source=RouteSuccessfulSave")
            if self._window_fingerprint() != before:
                self._print_window_dump()
        except asyncio.CancelledError:
            raise
        finally:
            if self._route_refresh_task is asyncio.current_task():
                self._route_refresh_task = None

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

    async def _sync_live_track(self) -> None:
        async with self._lock:
            await self._sync_live_track_locked()

    async def _sync_live_track_locked(self) -> None:
        live_key = self.window.map_focus_key
        if live_key is None:
            if self.hubs.track_ride_id is not None:
                await self.hubs.stop_track()
            return
        ride = self.window.rides.get(live_key) or {}
        if not status_live(str(ride.get("status") or "")):
            if self.hubs.track_ride_id is not None:
                await self.hubs.stop_track()
            return
        await self._cmd_track_locked(ride)

    async def _cmd_track_locked(self, ride: dict[str, Any]) -> None:
        resolved = self._resolved_from_day(ride)
        if resolved is None:
            return
        ride_id, details = resolved
        if self.hubs.track_ride_id == ride_id:
            return
        status = str(ride.get("status") or details.get("status") or "")
        if not status_live(status):
            return
        try:
            path = await self.mobile.monitoring_path(ride_id)
        except (ApiError, Exception) as exc:
            _LOGGER.warning(
                f"monitoring path failed ride={partial_id(str(ride_id))}: {exc}"
            )
            path = []
        self._print_path_snapshot(path)
        hub_ok = True
        try:
            await self.hubs.start_track(ride_id, self._hub_event)
        except Exception as exc:
            hub_ok = False
            _LOGGER.error(f"Dashboard hub failed: {exc}")
        snapshot = MonitoredPath(path)
        _LOGGER.info(
            f"live tracking started ride={partial_id(str(ride_id))} "
            f"source=signalr hub={'on' if hub_ok else 'failed'} "
            f"seeded={len(snapshot.points)} point(s)"
        )
        _LOGGER.debug(f"path groups {snapshot.sources}")

    async def _shutdown_passenger(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._route_refresh_task is not None:
            self._route_refresh_task.cancel()
            self._route_refresh_task = None
        await self.hubs.stop_mobile()
        await self.hubs.stop_track()

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_delay())
            before = self._window_fingerprint()
            await self._load_window()
            await self._sync_live_track()
            if self._window_fingerprint() != before:
                self._print_window_dump()

    async def _passenger_listen(self) -> int:
        await self._load_passenger_context()
        self._session_banner()
        await self.hubs.start_mobile(self._mobile_hub_event)
        await self._load_window()
        await self._sync_live_track()
        self._print_window_dump()
        print("Listening for ride updates (Ctrl+C to exit).")
        self._poll_task = asyncio.create_task(self._poll_loop(), name="RidePoll")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown_passenger()
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Traffical / Shift console login")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete data/config.json and start from the phone prompt",
    )
    return parser.parse_args()


async def async_main() -> int:
    _load_repo_dotenv()
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
        return await App(store, identity, mobile, hubs).run(clean=args.clean)
    finally:
        await session.close()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
