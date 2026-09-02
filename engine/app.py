from __future__ import annotations

import logging
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any

from engine.api_client import ApiError
from engine.consts import CONFIG_PATH, DEFAULT_ENVIRONMENT
from engine.helpers import create_pkce, prompt
from engine.identity_client import IdentityClient
from engine.mobile_client import MobileClient, rides_customer_type
from engine.session_store import SessionStore
from engine.signalr_client import SignalRHubs

logger = logging.getLogger(__name__)

AUTO_TRACK_INTERVAL_S = 30.0


class App:
    def __init__(
        self,
        store: SessionStore,
        identity: IdentityClient,
        mobile: MobileClient,
    ) -> None:
        self.store = store
        self.identity = identity
        self.mobile = mobile
        self.hubs: SignalRHubs | None = None
        self.day_date: str | None = None
        self.day_rides: list[dict[str, Any]] = []
        self.auto_track = False
        self._track_lock = threading.RLock()
        self._auto_stop = threading.Event()
        self._auto_thread: threading.Thread | None = None
        self.mobile.on_unauthorized = self._try_refresh
        self.identity.on_unauthorized = self._try_refresh

    def run(self, clean: bool = False, env: str | None = None) -> int:
        if clean:
            if self.store.clear():
                logger.info(f"Removed session file {CONFIG_PATH}")
            else:
                logger.info("No saved session to clear")

        self.store.load()
        if not self.store.identity_url:
            self.store.apply_environment(env or DEFAULT_ENVIRONMENT)
            self.store.save()
        elif env and env != self.store.environment:
            logger.warning(
                f"Saved session is {self.store.environment}. Use --clean to switch to {env}."
            )

        self.identity.base_url = self.store.identity_url.rstrip("/")
        self.identity.language = self.store.language
        self.mobile.base_url = self.store.api_url.rstrip("/")
        self.mobile.language = self.store.language

        if self._resume_logged_in():
            return self._passenger_menu()

        if self.store.phone:
            logger.info(f"Saved phone {self.store.phone}; skipping to OTP")
            self._otp_step(request_if_missing=True)
            return self._passenger_menu()

        self._collect_phone()
        self._request_otp()
        self._otp_step(request_if_missing=False)
        return self._passenger_menu()

    def _log_logged_in(self) -> None:
        user = self.store.user
        person = user.get("person") or {}
        name = " ".join(p for p in (person.get("firstName"), person.get("lastName")) if p)
        logger.info(
            f"Logged in environment={self.store.environment} phone={self.store.phone} "
            f"name={name} role={person.get('role')} memberId={person.get('memberId')} "
            f"session={CONFIG_PATH}"
        )

    def _request_otp(self) -> None:
        try:
            ticket, expired_in = self.identity.request_otp(self.store.phone, self.store.app_hash)
        except ApiError as exc:
            logger.error(f"{exc}")
            raise SystemExit(str(exc)) from exc
        self.store.set_otp(ticket, expired_in)
        self.store.save()
        logger.info(f"OTP requested for {self.store.phone}")
        if expired_in is not None:
            logger.debug(f"OTP expiredIn={expired_in} seconds")

    def _try_refresh(self) -> bool:
        with self._track_lock:
            refresh = self.store.tokens.get("refresh_token")
            if not refresh:
                return False
            try:
                body = self.identity.refresh(refresh)
            except ApiError as exc:
                logger.error(f"Refresh failed: {exc}")
                return False
            self.store.set_tokens(body)
            self.store.save()
            logger.info("Access token refreshed")
            return True

    def _resume_logged_in(self) -> bool:
        if not self.store.tokens.get("access_token"):
            return False

        try:
            user = self.identity.userinfo()
        except PermissionError:
            logger.warning("Access token rejected; trying refresh")
            if not self._try_refresh():
                self.store.clear_tokens()
                self.store.save()
                return False
            try:
                user = self.identity.userinfo()
            except (PermissionError, ApiError) as exc:
                logger.error(f"Still not authenticated: {exc}")
                self.store.clear_tokens()
                self.store.save()
                return False
        except ApiError as exc:
            logger.error(f"userinfo failed: {exc}")
            return False

        self.store.set_user(user)
        self.store.save()
        self._log_logged_in()
        return True

    def _collect_phone(self) -> None:
        phone = prompt("Phone number: ")
        if not phone:
            logger.error("Phone is required.")
            raise SystemExit("Phone is required.")
        self.store.phone = phone
        self.store.save()

    def _otp_step(self, request_if_missing: bool) -> None:
        if request_if_missing and not self.store.otp_ticket:
            self._request_otp()

        print(f"OTP for {self.store.phone}")
        print("Enter the code, or type 'r' to request a new OTP.")
        otp = prompt("OTP: ")
        if otp.lower() == "r":
            self._request_otp()
            otp = prompt("OTP: ")
        if not otp or otp.lower() == "r":
            logger.error("OTP is required.")
            raise SystemExit("OTP is required.")

        verifier, challenge = create_pkce()
        try:
            code = self.identity.authorize(
                self.store.phone,
                otp,
                self.store.otp_ticket,
                challenge,
                self.store.device_id,
            )
        except ApiError as exc:
            logger.warning(f"Authorize failed: {exc}")
            logger.info("Requesting a new OTP")
            self._request_otp()
            otp = prompt("OTP: ")
            if not otp:
                logger.error("OTP is required.")
                raise SystemExit("OTP is required.")
            verifier, challenge = create_pkce()
            code = self.identity.authorize(
                self.store.phone,
                otp,
                self.store.otp_ticket,
                challenge,
                self.store.device_id,
            )

        token_body = self.identity.exchange_code(code, verifier, retry_redirect=True)
        self.store.set_tokens(token_body)
        self.store.clear_otp()
        self.store.save()

        user = self.identity.userinfo()
        self.store.set_user(user)
        self.store.save()
        self._log_logged_in()

    def _policy_flag(self, policies: dict, group: str, key: str = "isActive") -> Any:
        block = policies.get(group) or {}
        if isinstance(block, dict):
            return block.get(key)
        return None

    def _load_passenger_context(self) -> None:
        try:
            roles = self.mobile.user_roles()
            self.store.set_roles(roles)
            self.store.save()
            logger.info(f"Loaded {len(roles) if isinstance(roles, list) else 1} role group(s)")
        except (ApiError, Exception) as exc:
            logger.error(f"User/Roles failed: {exc}")

        try:
            policies = self.mobile.passenger_policies()
        except (ApiError, Exception) as exc:
            logger.error(f"Passenger policies failed: {exc}")
            return
        if not isinstance(policies, dict):
            policies = {}
        self.store.set_policies(policies)
        self.store.save()
        logger.info(
            f"PassengerPolicy isReservationEnabled={policies.get('isReservationEnabled')} "
            f"reservation.isActive={self._policy_flag(policies, 'reservation')} "
            f"gotOnRideReport.isActive={self._policy_flag(policies, 'gotOnRideReport')} "
            f"notComingReport.isActive={self._policy_flag(policies, 'notComingReport')} "
            f"joinRide.isActive={self._policy_flag(policies, 'joinRide')}"
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
        name = (info.get("driver") or "").strip()
        return name

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

    def _is_your_station(self, station: dict[str, Any], passenger_stop: str, member_id: int | None) -> bool:
        name = (station.get("name") or station.get("stationName") or "").strip()
        if passenger_stop and name == passenger_stop.strip():
            return True
        if member_id is None:
            return False
        passengers = station.get("passengers") or []
        if not isinstance(passengers, list):
            return False
        for passenger in passengers:
            if not isinstance(passenger, dict):
                continue
            try:
                if int(passenger.get("id")) == member_id:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _station_label(self, station: dict[str, Any]) -> str:
        name = (station.get("name") or station.get("stationName") or "").strip()
        address = str(station.get("address") or "").strip()
        if station.get("isTarget"):
            return name or address
        return address or name

    def _view_suffix(self, status: str) -> str:
        key = status.casefold()
        if key in ("ongoing", "ongoingmonitored"):
            return "live"
        if key in ("finished", "finishedmonitored"):
            return "finished, no live GPS"
        return "GPS starts when ongoing"

    def _load_day(self, date_str: str) -> None:
        customer_type = self._customer_type_path()
        try:
            rides = self.mobile.list_rides(customer_type, date_str)
        except (ApiError, Exception) as exc:
            logger.error(f"List rides failed: {exc}")
            with self._track_lock:
                self.day_date = date_str
                self.day_rides = []
            return
        if not isinstance(rides, list):
            rides = []
        ride_ids: list[int] = []
        for ride in rides:
            info = ride.get("rideInfo") or {}
            ride_id = info.get("rideId") or ride.get("rideId")
            if ride_id is not None:
                try:
                    ride_ids.append(int(ride_id))
                except (TypeError, ValueError):
                    pass
        statuses: dict[int, dict] = {}
        if ride_ids:
            try:
                raw = self.mobile.checkin_statuses(ride_ids)
                if isinstance(raw, list):
                    for item in raw:
                        rid = item.get("rideId")
                        if rid is not None:
                            try:
                                statuses[int(rid)] = item
                            except (TypeError, ValueError):
                                pass
            except (ApiError, Exception) as exc:
                logger.error(f"Check-in statuses failed: {exc}")
        logger.info(f"{len(rides)} ride(s) for {date_str} ({customer_type})")
        built: list[dict[str, Any]] = []
        for i, ride in enumerate(rides, start=1):
            info = ride.get("rideInfo") if isinstance(ride.get("rideInfo"), dict) else {}
            ticket = str(info.get("rideTicket") or ride.get("rideTicket") or "")
            ride_id_raw = info.get("rideId") or ride.get("rideId")
            ride_id: int | None
            try:
                ride_id = int(ride_id_raw) if ride_id_raw is not None else None
            except (TypeError, ValueError):
                ride_id = None
            details: dict[str, Any] = {}
            if ticket:
                try:
                    loaded = self.mobile.ride_details(ticket)
                    if isinstance(loaded, dict):
                        details = loaded
                        if ride_id is None:
                            try:
                                ride_id = int(details.get("rideId"))
                            except (TypeError, ValueError):
                                ride_id = None
                except (ApiError, Exception) as exc:
                    logger.error(f"Ride details failed for ride {i}: {exc}")
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
        with self._track_lock:
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
        stop_plan = self._clock(info.get("passengerStationArrivalDateTime"))
        your_actual = ""
        your_stop_label = passenger_stop
        stations = details.get("stations") if isinstance(details.get("stations"), list) else []
        for station in stations:
            if isinstance(station, dict) and self._is_your_station(station, passenger_stop, member_id):
                your_actual = self._clock(station.get("actualArriveDateTime"))
                your_stop_label = self._station_label(station) or passenger_stop
                break
        timing = ""
        if stop_plan and your_actual:
            timing = f" (plan {stop_plan}, actual {your_actual})"
        elif stop_plan:
            timing = f" (plan {stop_plan})"
        driver = self._driver_name(details, info) or "—"
        shuttle = (details.get("shuttleCompanyName") or info.get("shuttleCompany") or "—")
        print()
        print(f"── Ride {item.get('index')}  {name}")
        print(f"    {start}–{end}  {status}  check-in: {check_s}")
        if your_stop_label:
            print(f"    Your stop: {your_stop_label}{timing}")
        print(f"    Driver {driver}  ·  {shuttle}")
        if not stations:
            print("    Stations: (none)")
            return
        print("    Stations:")
        for station in stations:
            if not isinstance(station, dict):
                print(f"      {station}")
                continue
            planned = self._clock(station.get("arrivalTime") or station.get("time"))
            actual = self._clock(station.get("actualArriveDateTime"))
            if actual and planned:
                time_col = f"{planned}  {actual}*"
            elif actual:
                time_col = f"{actual}*"
            else:
                time_col = planned or ""
            lat = station.get("lat")
            lng = station.get("lng")
            coord = ""
            if lat is not None and lng is not None:
                coord = f"{lat},{lng}"
            sname = self._station_label(station)
            marks = []
            if self._is_your_station(station, passenger_stop, member_id):
                marks.append("← you")
            if station.get("isTarget"):
                marks.append("(destination)")
            extra = ("  " + " ".join(marks)) if marks else ""
            print(f"      {time_col:<14}  {coord:<22}  {sname}{extra}")

    def _hubs_active(self) -> bool:
        if self.hubs is None:
            return False
        return self.hubs.track_ride_id is not None or self.hubs.chat_ride_id is not None

    def _build_menu(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if self._hubs_active():
            items.append({"label": "Stop live GPS / chat", "action": "stop"})
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
        if self._ride_chat_enabled():
            for ride in self.day_rides:
                idx = ride.get("index")
                items.append({"label": f"Ride {idx} — chat", "action": "chat", "ride": ride})
                items.append(
                    {"label": f"Ride {idx} — send message", "action": "send", "ride": ride}
                )
        if self.auto_track:
            items.append(
                {
                    "label": "Auto-track changes (on; Stop appears after Enter)",
                    "action": "auto",
                }
            )
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

    def _change_date(self) -> None:
        raw = prompt("Date [YYYY-MM-DD]: ")
        if not raw:
            print("Date unchanged.")
            return
        try:
            date.fromisoformat(raw)
        except ValueError:
            print("Use YYYY-MM-DD.")
            return
        if self.hubs is not None:
            with self._track_lock:
                self.hubs.stop_all()
        self._load_day(raw)
        self._print_day_dump()

    def _parse_utc(self, value: Any) -> datetime | None:
        if not value or not isinstance(value, str):
            return None
        text = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _chat_window_open(self, settings: dict[str, Any]) -> tuple[bool, str]:
        if not settings.get("isEnabled"):
            return False, "Ride chat is disabled for this ride"
        now = datetime.now(timezone.utc)
        start = self._parse_utc(settings.get("startDateTimeUtc"))
        end = self._parse_utc(settings.get("endDateTimeUtc"))
        if start and now < start:
            return False, f"Chat has not started yet (starts {settings.get('startDateTimeUtc')})"
        if end and now > end:
            return False, f"Chat window has ended (ended {settings.get('endDateTimeUtc')})"
        return True, "Chat window is open"

    def _ride_chat_enabled(self) -> bool:
        modules = (self.store.user or {}).get("modules") or {}
        return isinstance(modules, dict) and "rideChat" in modules

    def _require_ride_chat(self) -> bool:
        if self._ride_chat_enabled():
            return True
        print("Ride chat is not enabled for this customer (no rideChat module). The app hides the chat tab.")
        return False

    def _ride_from_ticket(self, ticket: str) -> tuple[int, dict[str, Any]] | None:
        try:
            details = self.mobile.ride_details(ticket)
        except (ApiError, Exception) as exc:
            logger.error(f"Ride details failed: {exc}")
            return None
        if not isinstance(details, dict):
            logger.error("Ride details response was not an object")
            return None
        try:
            ride_id = int(details.get("rideId"))
        except (TypeError, ValueError):
            logger.error("Ride details had no rideId")
            return None
        return ride_id, details

    def _print_path_snapshot(self, path: Any) -> None:
        if not path:
            print("No monitoring path yet (ride may not be live).")
            return
        points = path if isinstance(path, list) else [path]
        print(f"Monitoring path points: {len(points)}")
        for point in points[-5:]:
            if isinstance(point, dict):
                lat = point.get("latitude") or point.get("lat") or point.get("Latitude")
                lng = point.get("longitude") or point.get("lng") or point.get("Longitude")
                when = (
                    point.get("dateTime")
                    or point.get("createdAt")
                    or point.get("time")
                    or point.get("DateTime")
                )
                print(f"  {when} lat={lat} lng={lng}")
            else:
                print(f"  {point}")

    def _print_track_event(self, event: str, payload: Any) -> None:
        if event == "ArrivedToStation":
            station_id = payload.get("stationId") if isinstance(payload, dict) else payload
            print(f"[track] ArrivedToStation stationId={station_id}")
            return
        if isinstance(payload, dict):
            lat = payload.get("latitude") or payload.get("lat")
            lng = payload.get("longitude") or payload.get("lng")
            print(f"[track] {event} lat={lat} lng={lng}")
            return
        print(f"[track] {event} {payload}")

    def _print_chat_event(self, event: str, payload: Any) -> None:
        if isinstance(payload, dict):
            sender = " ".join(
                p for p in (payload.get("senderFirstName"), payload.get("senderLastName")) if p
            ) or payload.get("senderMemberId") or "unknown"
            text = payload.get("message") or payload
            print(f"[chat] {sender}: {text}")
            return
        print(f"[chat] {event} {payload}")

    def _print_chat_history(self, history: Any) -> None:
        items = history if isinstance(history, list) else []
        if not items:
            print("No chat history.")
            return
        print(f"Chat history ({len(items)}):")
        for item in items:
            if isinstance(item, dict):
                sender = " ".join(
                    p for p in (item.get("senderFirstName"), item.get("senderLastName")) if p
                ) or item.get("senderMemberId") or "?"
                print(f"  {item.get('createdAtUtc') or ''} {sender}: {item.get('message')}")
            else:
                print(f"  {item}")

    def _ensure_hubs(self) -> SignalRHubs:
        if self.hubs is None:
            self.hubs = SignalRHubs(self.store.api_url, lambda: self.store.tokens)
        return self.hubs

    def _resolved_from_day(self, ride: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
        details = ride.get("details") if isinstance(ride.get("details"), dict) else {}
        ride_id = ride.get("ride_id")
        if ride_id is None:
            ticket = ride.get("ticket") or ""
            if not ticket:
                logger.error("Ride has no ticket or rideId")
                return None
            return self._ride_from_ticket(str(ticket))
        try:
            return int(ride_id), details
        except (TypeError, ValueError):
            logger.error("Ride had no rideId")
            return None

    def _cmd_track(self, ride: dict[str, Any]) -> None:
        with self._track_lock:
            self._cmd_track_locked(ride)

    def _cmd_track_locked(self, ride: dict[str, Any]) -> None:
        resolved = self._resolved_from_day(ride)
        if resolved is None:
            return
        ride_id, details = resolved
        status = str(ride.get("status") or details.get("status") or "")
        status_key = status.casefold()
        try:
            path = self.mobile.monitoring_path(ride_id)
        except (ApiError, Exception) as exc:
            logger.error(f"Monitoring path failed: {exc}")
            path = []
        self._print_path_snapshot(path)
        live = status_key in ("ongoing", "ongoingmonitored")
        finished = status_key in ("finished", "finishedmonitored")
        if live:
            try:
                self._ensure_hubs().start_track(ride_id, self._print_track_event)
                print("Listening for live coordinates. Stop will appear in the next menu.")
            except Exception as exc:
                logger.error(f"Dashboard hub failed: {exc}")
            return
        if finished:
            print(f"Ride status is {status}; live GPS has ended. Showing path snapshot only.")
            return
        print(
            f"Ride status is {status or 'unknown'}; live GPS starts when the ride is ongoing."
        )

    def _cmd_chat(self, ride: dict[str, Any]) -> None:
        if not self._require_ride_chat():
            return
        resolved = self._resolved_from_day(ride)
        if resolved is None:
            return
        ride_id, _details = resolved
        try:
            settings = self.mobile.chat_settings(ride_id)
        except ApiError as exc:
            if exc.status_code == 403:
                logger.error("Chat is disabled for this ride or tenant (403).")
                return
            logger.error(f"Chat settings failed: {exc}")
            return
        except Exception as exc:
            logger.error(f"Chat settings failed: {exc}")
            return
        if not isinstance(settings, dict):
            settings = {}
        open_now, reason = self._chat_window_open(settings)
        logger.info(
            f"Chat isEnabled={settings.get('isEnabled')} "
            f"start={settings.get('startDateTimeUtc')} end={settings.get('endDateTimeUtc')} "
            f"{reason}"
        )
        try:
            history = self.mobile.chat_history(ride_id)
        except (ApiError, Exception) as exc:
            logger.error(f"Chat history failed: {exc}")
            history = []
        self._print_chat_history(history)
        if not open_now:
            print(reason)
            return
        try:
            self._ensure_hubs().start_chat(ride_id, self._print_chat_event)
            print("Listening for chat. Stop will appear in the next menu.")
        except Exception as exc:
            logger.error(f"Chat hub failed: {exc}")

    def _cmd_chat_send(self, ride: dict[str, Any], text: str) -> None:
        if not text:
            print("Send cancelled.")
            return
        if not self._require_ride_chat():
            return
        resolved = self._resolved_from_day(ride)
        if resolved is None:
            return
        ride_id, _details = resolved
        hubs = self._ensure_hubs()
        if not hubs.chat_connected(ride_id):
            try:
                settings = self.mobile.chat_settings(ride_id)
            except ApiError as exc:
                if exc.status_code == 403:
                    logger.error("Chat is disabled for this ride or tenant (403).")
                    return
                logger.error(f"Chat settings failed: {exc}")
                return
            except Exception as exc:
                logger.error(f"Chat settings failed: {exc}")
                return
            if not isinstance(settings, dict):
                settings = {}
            open_now, reason = self._chat_window_open(settings)
            if not open_now:
                print(reason)
                return
            try:
                hubs.start_chat(ride_id, self._print_chat_event)
            except Exception as exc:
                logger.error(f"Chat hub failed: {exc}")
                return
        try:
            hubs.send_chat(str(uuid.uuid4()), text)
            logger.info("Chat message sent")
        except Exception as exc:
            logger.error(f"SendMessage failed: {exc}")

    def _cmd_stop(self) -> None:
        with self._track_lock:
            if self.hubs is None:
                print("No live hubs.")
                return
            self.hubs.stop_all()
            print("Stopped track and chat hubs.")

    def _list_row_ids(self, row: dict[str, Any]) -> tuple[str, int | None]:
        info = row.get("rideInfo") if isinstance(row.get("rideInfo"), dict) else {}
        ticket = str(info.get("rideTicket") or row.get("rideTicket") or "")
        ride_id_raw = info.get("rideId") or row.get("rideId")
        try:
            ride_id = int(ride_id_raw) if ride_id_raw is not None else None
        except (TypeError, ValueError):
            ride_id = None
        return ticket, ride_id

    def _match_day_ride(self, ticket: str, ride_id: int | None) -> dict[str, Any] | None:
        for ride in self.day_rides:
            if ticket and ride.get("ticket") and ticket == ride.get("ticket"):
                return ride
            cached_id = ride.get("ride_id")
            if ride_id is not None and cached_id is not None and int(cached_id) == ride_id:
                return ride
        return None

    def _checkin_flag(self, check: Any) -> bool | None:
        if not isinstance(check, dict):
            return None
        return bool(check.get("checkIn"))

    def _status_live(self, status: str) -> bool:
        return status.casefold() in ("ongoing", "ongoingmonitored")

    def _status_finished(self, status: str) -> bool:
        return status.casefold() in ("finished", "finishedmonitored")

    def _toggle_auto_track(self) -> None:
        if self.auto_track:
            self._stop_auto_track_poller()
            self.auto_track = False
            print("Auto-track off.")
            return
        self.auto_track = True
        self._start_auto_track_poller()
        print(f"Auto-track on (every {int(AUTO_TRACK_INTERVAL_S)}s).")

    def _start_auto_track_poller(self) -> None:
        if self._auto_thread is not None and self._auto_thread.is_alive():
            return
        self._auto_stop.clear()
        self._auto_thread = threading.Thread(
            target=self._auto_track_loop,
            name="AutoTrack",
            daemon=True,
        )
        self._auto_thread.start()

    def _stop_auto_track_poller(self) -> None:
        self._auto_stop.set()
        thread = self._auto_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._auto_thread = None

    def _shutdown_passenger(self) -> None:
        self.auto_track = False
        self._stop_auto_track_poller()
        with self._track_lock:
            if self.hubs is not None:
                self.hubs.stop_all()

    def _auto_track_loop(self) -> None:
        while not self._auto_stop.is_set():
            try:
                self._auto_track_tick()
            except Exception as exc:
                logger.error(f"Auto-track poll failed: {exc}")
            if self._auto_stop.wait(AUTO_TRACK_INTERVAL_S):
                break

    def _auto_track_tick(self) -> None:
        date_str = self.day_date
        if not date_str or not self.auto_track:
            return
        customer_type = self._customer_type_path()
        try:
            rides = self.mobile.list_rides(customer_type, date_str)
        except ApiError as exc:
            if exc.status_code == 401:
                print("Session expired. Auto-track off. Quit and log in again.")
                if self.auto_track:
                    self._toggle_auto_track()
                return
            logger.error(f"Auto-track list failed: {exc}")
            return
        except Exception as exc:
            logger.error(f"Auto-track list failed: {exc}")
            return
        if not isinstance(rides, list):
            rides = []
        ride_ids: list[int] = []
        for row in rides:
            _ticket, ride_id = self._list_row_ids(row)
            if ride_id is not None:
                ride_ids.append(ride_id)
        statuses: dict[int, dict] = {}
        if ride_ids:
            try:
                raw = self.mobile.checkin_statuses(ride_ids)
                if isinstance(raw, list):
                    for item in raw:
                        rid = item.get("rideId")
                        if rid is not None:
                            try:
                                statuses[int(rid)] = item
                            except (TypeError, ValueError):
                                pass
            except (ApiError, Exception) as exc:
                logger.error(f"Auto-track check-in failed: {exc}")
        start_view: dict[str, Any] | None = None
        with self._track_lock:
            for row in rides:
                ticket, ride_id = self._list_row_ids(row)
                cached = self._match_day_ride(ticket, ride_id)
                if cached is None:
                    continue
                new_status = str(row.get("status") or "")
                old_status = str(cached.get("status") or "")
                if new_status and new_status != old_status:
                    print(f"[auto] Ride {cached.get('index')} {old_status} → {new_status}")
                    cached["status"] = new_status
                    cached["list_row"] = row
                    details = cached.get("details")
                    if isinstance(details, dict):
                        details["status"] = new_status
                    hubs = self.hubs
                    if self._status_live(new_status) and not self._status_live(old_status):
                        if hubs is None or hubs.track_ride_id is None:
                            if start_view is None:
                                start_view = cached
                    if (
                        self._status_finished(new_status)
                        and hubs is not None
                        and hubs.track_ride_id == cached.get("ride_id")
                    ):
                        hubs.stop_track()
                        print(
                            f"[auto] Ride {cached.get('index')} live GPS ended "
                            "(finished). Stop will disappear after Enter."
                        )
                check = statuses.get(cached["ride_id"]) if cached.get("ride_id") is not None else None
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
                self._cmd_track_locked(start_view)

    def _passenger_menu(self) -> int:
        self._load_passenger_context()
        self._session_banner()
        self._load_day(date.today().isoformat())
        self._print_day_dump()
        while True:
            items = self._build_menu()
            self._print_menu(items)
            try:
                line = prompt("> ")
            except SystemExit:
                self._shutdown_passenger()
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
                self._shutdown_passenger()
                return 0
            if action == "stop":
                self._cmd_stop()
                continue
            if action == "view":
                self._cmd_track(picked["ride"])
                continue
            if action == "chat":
                self._cmd_chat(picked["ride"])
                continue
            if action == "send":
                text = prompt("Message: ")
                self._cmd_chat_send(picked["ride"], text)
                continue
            if action == "date":
                self._change_date()
                continue
            if action == "auto":
                self._toggle_auto_track()
                continue
            print("Enter a menu number.")
