"""ASP.NET Core SignalR client over aiohttp (HA-free)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import aiohttp

from ..common.consts import DASHBOARD_HUB, HTTP_TIMEOUT, SIGNALR_RECORD_SEP
from ..common.helpers import authorization_header, ssl_context

_LOGGER = logging.getLogger(__name__)

OnEvent = Callable[[str, Any], Awaitable[None] | None]


def _hub_http_url(api_url: str, hub_name: str) -> str:
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


def _to_ws_url(http_url: str) -> str:
    parsed = urlparse(http_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(parsed._replace(scheme=scheme))


class SignalRHubs:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str,
        tokens_provider: Callable[[], dict[str, Any] | None],
    ) -> None:
        self.session = session
        self.api_url = api_url.rstrip("/")
        self.tokens_provider = tokens_provider
        self.track_ride_id: int | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._on_event: OnEvent | None = None
        self._closed = asyncio.Event()

    def _access_token(self) -> str:
        tokens = self.tokens_provider() or {}
        return (tokens.get("access_token") or "").strip()

    async def start_track(self, ride_id: int, on_event: OnEvent) -> None:
        await self.stop_track()
        self._on_event = on_event
        self.track_ride_id = ride_id
        self._closed.clear()
        self._task = asyncio.create_task(
            self._run_dashboard(ride_id), name="traffical-signalr"
        )

    async def stop_track(self) -> None:
        self.track_ride_id = None
        self._closed.set()
        ws = self._ws
        self._ws = None
        if ws is not None and not ws.closed:
            await ws.close()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        _LOGGER.info("SignalR disconnected")

    async def _run_dashboard(self, ride_id: int) -> None:
        try:
            await self._connect_and_listen(ride_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Dashboard hub failed")
        finally:
            self._ws = None

    async def _negotiate(self, hub_url: str) -> dict[str, Any]:
        token = self._access_token()
        headers = {}
        if token:
            headers["Authorization"] = authorization_header(
                {"access_token": token, "token_type": "Bearer"}
            )
        negotiate_url = f"{hub_url}/negotiate"
        _LOGGER.debug(f"SignalR negotiate path={negotiate_url}")
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with self.session.post(
            negotiate_url,
            params={"negotiateVersion": "1"},
            headers=headers,
            timeout=timeout,
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(f"SignalR negotiate failed ({resp.status}): {text}")
            data = await resp.json(content_type=None)
        if not isinstance(data, dict):
            raise RuntimeError("SignalR negotiate returned no object")
        return data

    async def _connect_and_listen(self, ride_id: int) -> None:
        hub_url = _hub_http_url(self.api_url, DASHBOARD_HUB)
        negotiated = await self._negotiate(hub_url)
        connection_token = (
            negotiated.get("connectionToken") or negotiated.get("connectionId") or ""
        )
        url = negotiated.get("url") or hub_url
        token = self._access_token()
        query = {"id": connection_token}
        if token:
            query["access_token"] = token
        parsed = urlparse(str(url))
        sep = "&" if parsed.query else "?"
        ws_url = _to_ws_url(f"{url}{sep}{urlencode(query)}")
        _LOGGER.debug("SignalR connect attempt hub=MobileDashboardHub")
        self._ws = await self.session.ws_connect(
            ws_url,
            heartbeat=15,
            ssl=ssl_context(),
            timeout=HTTP_TIMEOUT,
        )
        handshake = json.dumps({"protocol": "json", "version": 1}) + SIGNALR_RECORD_SEP
        await self._ws.send_str(handshake)
        _LOGGER.info(f"SignalR connected rideId={ride_id}")
        invoke = {
            "type": 1,
            "target": "Monitor",
            "arguments": [ride_id],
        }
        await self._ws.send_str(json.dumps(invoke) + SIGNALR_RECORD_SEP)
        async for msg in self._ws:
            if self._closed.is_set():
                break
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._handle_text(msg.data)
            elif msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
                aiohttp.WSMsgType.CLOSE,
            ):
                break

    async def _handle_text(self, data: str) -> None:
        for raw in data.split(SIGNALR_RECORD_SEP):
            chunk = raw.strip()
            if not chunk:
                continue
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            msg_type = payload.get("type")
            if msg_type == 6:
                if self._ws is not None and not self._ws.closed:
                    await self._ws.send_str(
                        json.dumps({"type": 6}) + SIGNALR_RECORD_SEP
                    )
                continue
            if msg_type == 7:
                _LOGGER.warning("SignalR close frame")
                return
            target = payload.get("target")
            if not target:
                continue
            args = _parse_hub_args(payload.get("arguments"))
            on_event = self._on_event
            if on_event is None:
                continue
            result = on_event(str(target), args)
            if asyncio.iscoroutine(result):
                await result
