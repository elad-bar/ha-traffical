from __future__ import annotations

import json
import logging
import ssl
from typing import Any, Callable

from signalrcore.hub_connection_builder import HubConnectionBuilder

from engine.helpers import write_debug_json

logger = logging.getLogger(__name__)


def insecure_ssl_context() -> ssl.SSLContext:
    ctx = ssl._create_unverified_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _hub_url(api_url: str, hub_name: str) -> str:
    return f"{api_url.rstrip('/')}/{hub_name.lstrip('/')}"


def _parse_hub_args(args: Any) -> Any:
    if isinstance(args, (list, tuple)) and len(args) == 1:
        payload = args[0]
    else:
        payload = args
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
    return payload


class SignalRHubs:
    def __init__(self, api_url: str, tokens_provider: Callable[[], dict[str, Any] | None]) -> None:
        self.api_url = api_url
        self.tokens_provider = tokens_provider
        self._track = None
        self._chat = None
        self.track_ride_id: int | None = None
        self.chat_ride_id: int | None = None

    def _access_token(self) -> str:
        tokens = self.tokens_provider() or {}
        return (tokens.get("access_token") or "").strip()

    def _build(self, hub_name: str, extra_headers: dict[str, str] | None = None):
        headers = extra_headers.copy() if extra_headers else {}
        url = _hub_url(self.api_url, hub_name)
        builder = (
            HubConnectionBuilder()
            .with_url(
                url,
                options={
                    "access_token_factory": self._access_token,
                    "ssl_context": insecure_ssl_context(),
                    "headers": headers,
                },
            )
            .configure_logging(logging.WARNING)
        )
        return builder.build()

    def start_track(self, ride_id: int, on_event: Callable[[str, Any], None]) -> None:
        self.stop_track()
        conn = self._build("MobileDashboardHub")

        def on_open() -> None:
            logger.info(f"Dashboard hub connected; Monitor rideId={ride_id}")
            try:
                conn.send("Monitor", [ride_id])
            except Exception as exc:
                logger.error(f"Monitor invoke failed: {exc}")

        def make_handler(event: str):
            def handler(args: Any) -> None:
                payload = _parse_hub_args(args)
                write_debug_json(
                    "mobile_track_event",
                    {"name": "mobile_track_event", "event": event, "payload": payload},
                )
                on_event(event, payload)

            return handler

        conn.on_open(on_open)
        conn.on("ReceiveCoordinates", make_handler("ReceiveCoordinates"))
        conn.on("ArrivedToStation", make_handler("ArrivedToStation"))
        conn.on_error(lambda data: logger.error(f"Dashboard hub error: {data}"))
        conn.start()
        self._track = conn
        self.track_ride_id = ride_id

    def start_chat(self, ride_id: int, on_event: Callable[[str, Any], None]) -> None:
        self.stop_chat()
        conn = self._build("mobileRideChatHub", extra_headers={"rideId": str(ride_id)})

        def make_handler(event: str):
            def handler(args: Any) -> None:
                payload = _parse_hub_args(args)
                write_debug_json(
                    "mobile_chat_event",
                    {"name": "mobile_chat_event", "event": event, "payload": payload},
                )
                on_event(event, payload)

            return handler

        conn.on_open(lambda: logger.info(f"Chat hub connected rideId={ride_id}"))
        conn.on("OnNewMessage", make_handler("OnNewMessage"))
        conn.on("OnDeleteMessage", make_handler("OnDeleteMessage"))
        conn.on_error(lambda data: logger.error(f"Chat hub error: {data}"))
        conn.start()
        self._chat = conn
        self.chat_ride_id = ride_id

    def chat_connected(self, ride_id: int) -> bool:
        return self._chat is not None and self.chat_ride_id == ride_id

    def send_chat(self, message_id: str, message: str) -> None:
        if self._chat is None:
            raise RuntimeError("Chat hub is not connected.")
        self._chat.send("SendMessage", [message_id, message])

    def stop_track(self) -> None:
        if self._track is not None:
            try:
                self._track.stop()
            except Exception as exc:
                logger.warning(f"Stop dashboard hub: {exc}")
            self._track = None
            self.track_ride_id = None

    def stop_chat(self) -> None:
        if self._chat is not None:
            try:
                self._chat.stop()
            except Exception as exc:
                logger.warning(f"Stop chat hub: {exc}")
            self._chat = None
            self.chat_ride_id = None

    def stop_all(self) -> None:
        self.stop_track()
        self.stop_chat()
