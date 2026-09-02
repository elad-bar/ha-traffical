"""ASP.NET Core SignalR client over aiohttp (HA-free)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

from ..common.consts import (
    DASHBOARD_HUB,
    HTTP_TIMEOUT,
    MOBILE_HUB,
    SIGNALR_RECORD_SEP,
)
from ..common.helpers import authorization_header, now_iso, ssl_context

_LOGGER = logging.getLogger(__name__)

OnEvent = Callable[[str, Any], Awaitable[None] | None]

# Azure SignalR answers the first negotiate with a redirect, so one hop is the
# norm; the cap only guards against a redirect loop.
MAX_NEGOTIATE_REDIRECTS = 5

# The hub can stay connected while delivering nothing, so report what it has
# actually sent on a fixed cadence instead of only at disconnect.
HUB_HEARTBEAT_S = 30.0
HUB_RECONNECT_S = 5.0

_TOKEN_QUERY_RE = re.compile(r"((?:access_token|accessToken)=)[^&\s'\"]+")


def _redact(text: str) -> str:
    """Strip bearer tokens so failed URLs are safe to log."""
    return _TOKEN_QUERY_RE.sub(r"\1<redacted>", text)


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


def _negotiate_url(url: str) -> str:
    """Append ``/negotiate`` to the path, preserving any existing query."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["negotiateVersion"] = "1"
    return urlunparse(parsed._replace(path=f"{path}negotiate", query=urlencode(params)))


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
        self._frames: dict[str, int] = {}
        self._mobile_ws: aiohttp.ClientWebSocketResponse | None = None
        self._mobile_task: asyncio.Task[None] | None = None
        self._mobile_on_event: OnEvent | None = None
        self._mobile_closed = asyncio.Event()
        self._mobile_frames: dict[str, int] = {}
        self._dashboard_diag: dict[str, Any] = {}
        self._mobile_diag: dict[str, Any] = {}

    def _ws_open(self, ws: aiohttp.ClientWebSocketResponse | None) -> bool:
        return ws is not None and not ws.closed

    def _task_running(self, task: asyncio.Task[None] | None) -> bool:
        return task is not None and not task.done()

    def _hub_snapshot(
        self,
        diag: dict[str, Any],
        *,
        frames: dict[str, int],
        ws: aiohttp.ClientWebSocketResponse | None,
        task: asyncio.Task[None] | None,
    ) -> dict[str, Any]:
        invocations = sum(
            count for kind, count in frames.items() if kind.startswith("invocation:")
        )
        return {
            "ws_open": self._ws_open(ws),
            "task_running": self._task_running(task),
            "last_negotiate_status": diag.get("last_negotiate_status"),
            "negotiate_hops": diag.get("negotiate_hops"),
            "last_error": diag.get("last_error"),
            "last_event": diag.get("last_event"),
            "last_event_at": diag.get("last_event_at"),
            "invocations": invocations,
            "frames": dict(frames),
        }

    def snapshot_for_diagnostics(self) -> dict[str, Any]:
        """Hub health for HA diagnostics (no GPS, no tokens)."""
        dashboard = self._hub_snapshot(
            self._dashboard_diag,
            frames=self._frames,
            ws=self._ws,
            task=self._task,
        )
        dashboard["track_ride_id"] = self.track_ride_id
        return {
            "dashboard": dashboard,
            "mobile": self._hub_snapshot(
                self._mobile_diag,
                frames=self._mobile_frames,
                ws=self._mobile_ws,
                task=self._mobile_task,
            ),
        }

    def _tally(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in sorted(self._frames.items())) or "none"

    @property
    def invocations(self) -> int:
        """Server pushes received on the current subscription."""
        return sum(
            count
            for kind, count in self._frames.items()
            if kind.startswith("invocation:")
        )

    def _invocations(self) -> int:
        return self.invocations

    async def _heartbeat_loop(self, ride_id: int) -> None:
        while not self._closed.is_set():
            try:
                await asyncio.wait_for(self._closed.wait(), HUB_HEARTBEAT_S)
                return
            except asyncio.TimeoutError:
                pass
            _LOGGER.info(
                f"SignalR alive rideId={ride_id} invocations={self._invocations()} "
                f"frames[{self._tally()}]"
            )

    def _access_token(self) -> str:
        tokens = self.tokens_provider() or {}
        return (tokens.get("access_token") or "").strip()

    async def start_mobile(self, on_event: OnEvent) -> None:
        """Keep the user-scoped ride-list hub connected."""
        await self.stop_mobile()
        self._mobile_on_event = on_event
        self._mobile_closed.clear()
        self._mobile_frames = {}
        self._mobile_task = asyncio.create_task(
            self._run_mobile(), name="traffical-signalr-mobile"
        )

    async def stop_mobile(self) -> None:
        """Stop the user-scoped ride-list hub."""
        self._mobile_closed.set()
        ws = self._mobile_ws
        self._mobile_ws = None
        if ws is not None and not ws.closed:
            await ws.close()
        task = self._mobile_task
        self._mobile_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if ws is not None or task is not None:
            _LOGGER.info("SignalR mobile disconnected")

    async def restart(self) -> None:
        """Reconnect active hubs after the authenticated identity changes."""
        mobile_on_event = self._mobile_on_event
        track_on_event = self._on_event
        ride_id = self.track_ride_id
        if mobile_on_event is not None:
            await self.start_mobile(mobile_on_event)
        if ride_id is not None and track_on_event is not None:
            await self.start_track(ride_id, track_on_event)

    async def start_track(self, ride_id: int, on_event: OnEvent) -> None:
        await self.stop_track()
        self._on_event = on_event
        self.track_ride_id = ride_id
        self._closed.clear()
        self._frames = {}
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
        if ws is not None or task is not None:
            # Frame tally makes "the hub pushed nothing" verifiable instead of
            # inferred from an absence of log lines.
            _LOGGER.info(
                f"SignalR disconnected invocations={self._invocations()} "
                f"frames[{self._tally()}]"
            )

    async def _run_dashboard(self, ride_id: int) -> None:
        while not self._closed.is_set():
            try:
                await self._connect_and_listen(ride_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._dashboard_diag["last_error"] = _redact(str(exc))
                _LOGGER.exception("Dashboard hub failed")
            finally:
                self._ws = None
            if self._closed.is_set():
                return
            _LOGGER.warning(
                f"SignalR reconnecting hub={DASHBOARD_HUB} in={HUB_RECONNECT_S:g}s"
            )
            try:
                await asyncio.wait_for(self._closed.wait(), HUB_RECONNECT_S)
            except asyncio.TimeoutError:
                pass

    async def _run_mobile(self) -> None:
        while not self._mobile_closed.is_set():
            try:
                await self._connect_mobile()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._mobile_diag["last_error"] = _redact(str(exc))
                _LOGGER.exception("Mobile hub failed")
            finally:
                self._mobile_ws = None
            if self._mobile_closed.is_set():
                return
            _LOGGER.warning(
                f"SignalR reconnecting hub={MOBILE_HUB} in={HUB_RECONNECT_S:g}s"
            )
            try:
                await asyncio.wait_for(self._mobile_closed.wait(), HUB_RECONNECT_S)
            except asyncio.TimeoutError:
                pass

    async def _negotiate(
        self, hub_url: str, token: str, diag: dict[str, Any]
    ) -> dict[str, Any]:
        headers = {}
        if token:
            headers["Authorization"] = authorization_header(
                {"access_token": token, "token_type": "Bearer"}
            )
        negotiate_url = _negotiate_url(hub_url)
        _LOGGER.debug(f"SignalR negotiate path={_redact(negotiate_url)}")
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with self.session.post(
            negotiate_url,
            headers=headers,
            timeout=timeout,
        ) as resp:
            diag["last_negotiate_status"] = resp.status
            if resp.status >= 400:
                text = await resp.text()
                redacted = _redact(text)
                diag["last_error"] = f"negotiate ({resp.status}): {redacted}"
                raise RuntimeError(
                    f"SignalR negotiate failed ({resp.status}): {redacted}"
                )
            data = await resp.json(content_type=None)
        if not isinstance(data, dict):
            diag["last_error"] = "negotiate returned no object"
            raise RuntimeError("SignalR negotiate returned no object")
        return data

    async def _negotiate_chain(
        self, hub_url: str, diag: dict[str, Any]
    ) -> tuple[str, str, str]:
        """Resolve the connect URL, connection token and access token.

        Azure SignalR replies to the first negotiate with a redirect carrying a
        service ``url`` and its own ``accessToken``. The ``connectionToken``
        only comes back from the negotiate against that service URL, and the
        service token — not the app token — authenticates the websocket.
        """
        url = hub_url
        token = self._access_token()
        hops = 0
        for _ in range(MAX_NEGOTIATE_REDIRECTS):
            data = await self._negotiate(url, token, diag)
            redirect = str(data.get("url") or "").strip()
            if redirect:
                hops += 1
                url = redirect
                token = str(data.get("accessToken") or "").strip() or token
                continue
            connection_token = str(
                data.get("connectionToken") or data.get("connectionId") or ""
            ).strip()
            if not connection_token:
                diag["last_error"] = "negotiate returned no connection token"
                raise RuntimeError("SignalR negotiate returned no connection token")
            diag["negotiate_hops"] = hops
            return url, connection_token, token
        diag["last_error"] = "negotiate redirected too many times"
        raise RuntimeError("SignalR negotiate redirected too many times")

    async def _connect_and_listen(self, ride_id: int) -> None:
        hub_url = _hub_http_url(self.api_url, DASHBOARD_HUB)
        url, connection_token, token = await self._negotiate_chain(
            hub_url, self._dashboard_diag
        )
        query = {"id": connection_token}
        if token:
            query["access_token"] = token
        parsed = urlparse(str(url))
        sep = "&" if parsed.query else "?"
        ws_url = _to_ws_url(f"{url}{sep}{urlencode(query)}")
        _LOGGER.debug("SignalR connect attempt hub=MobileDashboardHub")
        try:
            self._ws = await self.session.ws_connect(
                ws_url,
                heartbeat=15,
                ssl=ssl_context(),
                timeout=HTTP_TIMEOUT,
            )
        except aiohttp.WSServerHandshakeError as exc:
            # aiohttp embeds the full URL (and therefore the token) in the
            # message, so re-raise a redacted error and drop the cause.
            raise RuntimeError(
                f"SignalR websocket handshake failed ({exc.status}) "
                f"url={_redact(ws_url)}"
            ) from None
        except aiohttp.ClientError as exc:
            raise RuntimeError(
                f"SignalR websocket connect failed: {_redact(str(exc))}"
            ) from None
        handshake = json.dumps({"protocol": "json", "version": 1}) + SIGNALR_RECORD_SEP
        await self._ws.send_str(handshake)
        _LOGGER.info(f"SignalR connected rideId={ride_id}")
        # An invocationId makes this a blocking invoke, so the server answers
        # with a completion (type 3) carrying any error. Without it the send is
        # fire-and-forget and a rejected subscription looks identical to a
        # working one.
        invoke = {
            "type": 1,
            "invocationId": str(ride_id),
            "target": "Monitor",
            "arguments": [ride_id],
        }
        await self._ws.send_str(json.dumps(invoke) + SIGNALR_RECORD_SEP)
        beat = asyncio.create_task(
            self._heartbeat_loop(ride_id), name="traffical-signalr-beat"
        )
        try:
            async for msg in self._ws:
                if self._closed.is_set():
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_text(msg.data)
                elif msg.type is aiohttp.WSMsgType.BINARY:
                    # Would mean the server ignored our JSON handshake.
                    _LOGGER.warning(f"SignalR binary frame bytes={len(msg.data)}")
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    _LOGGER.info(f"SignalR socket closed by peer type={msg.type.name}")
                    break
        finally:
            beat.cancel()

    async def _connect_mobile(self) -> None:
        hub_url = _hub_http_url(self.api_url, MOBILE_HUB)
        url, connection_token, token = await self._negotiate_chain(
            hub_url, self._mobile_diag
        )
        query = {"id": connection_token}
        if token:
            query["access_token"] = token
        parsed = urlparse(str(url))
        sep = "&" if parsed.query else "?"
        ws_url = _to_ws_url(f"{url}{sep}{urlencode(query)}")
        _LOGGER.debug(f"SignalR connect attempt hub={MOBILE_HUB}")
        try:
            self._mobile_ws = await self.session.ws_connect(
                ws_url,
                heartbeat=15,
                ssl=ssl_context(),
                timeout=HTTP_TIMEOUT,
            )
        except aiohttp.WSServerHandshakeError as exc:
            raise RuntimeError(
                f"SignalR websocket handshake failed ({exc.status}) "
                f"url={_redact(ws_url)}"
            ) from None
        except aiohttp.ClientError as exc:
            raise RuntimeError(
                f"SignalR websocket connect failed: {_redact(str(exc))}"
            ) from None
        handshake = json.dumps({"protocol": "json", "version": 1}) + SIGNALR_RECORD_SEP
        await self._mobile_ws.send_str(handshake)
        _LOGGER.info(f"SignalR connected hub={MOBILE_HUB}")
        async for msg in self._mobile_ws:
            if self._mobile_closed.is_set():
                break
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._handle_mobile_text(msg.data)
            elif msg.type is aiohttp.WSMsgType.BINARY:
                _LOGGER.warning(
                    f"SignalR binary frame hub={MOBILE_HUB} bytes={len(msg.data)}"
                )
            elif msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
                aiohttp.WSMsgType.CLOSE,
            ):
                _LOGGER.info(
                    f"SignalR socket closed hub={MOBILE_HUB} type={msg.type.name}"
                )
                break

    async def _handle_mobile_text(self, data: str) -> None:
        for raw in data.split(SIGNALR_RECORD_SEP):
            chunk = raw.strip()
            if not chunk:
                continue
            try:
                frame = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if not isinstance(frame, dict):
                continue
            msg_type = frame.get("type")
            target = frame.get("target")
            kind = f"invocation:{target}" if target else f"type{msg_type}"
            self._mobile_frames[kind] = self._mobile_frames.get(kind, 0) + 1
            if msg_type is None:
                if frame.get("error"):
                    _LOGGER.error(
                        f"SignalR handshake rejected hub={MOBILE_HUB}: "
                        f"{frame['error']}"
                    )
                continue
            if msg_type == 6:
                if self._mobile_ws is not None and not self._mobile_ws.closed:
                    await self._mobile_ws.send_str(
                        json.dumps({"type": 6}) + SIGNALR_RECORD_SEP
                    )
                continue
            if msg_type == 7:
                _LOGGER.warning(
                    f"SignalR close frame hub={MOBILE_HUB} "
                    f"error={frame.get('error') or 'none'}"
                )
                return
            if msg_type != 1 or not target:
                continue
            if self._mobile_frames.get(kind) == 1:
                _LOGGER.info(f"SignalR first push hub={MOBILE_HUB} target={target}")
            self._mobile_diag["last_event"] = str(target)
            self._mobile_diag["last_event_at"] = now_iso()
            on_event = self._mobile_on_event
            if on_event is None:
                continue
            result = on_event(str(target), _parse_hub_args(frame.get("arguments")))
            if asyncio.iscoroutine(result):
                await result

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
            target = payload.get("target")
            kind = f"invocation:{target}" if target else f"type{msg_type}"
            self._frames[kind] = self._frames.get(kind, 0) + 1
            _LOGGER.debug(f"SignalR frame type={msg_type!r} target={target!r}")
            if msg_type is None:
                # Handshake response: ``{}`` on success, ``{"error": ...}`` on
                # rejection.
                if payload.get("error"):
                    _LOGGER.error(f"SignalR handshake rejected: {payload['error']}")
                continue
            if msg_type == 6:
                if self._ws is not None and not self._ws.closed:
                    await self._ws.send_str(
                        json.dumps({"type": 6}) + SIGNALR_RECORD_SEP
                    )
                continue
            if msg_type == 3:
                # Completion for our ``Monitor`` invoke. ``Monitor`` returns
                # void, so a clean completion proves the method ran, not that
                # the subscription was granted.
                if payload.get("error"):
                    _LOGGER.error(f"SignalR Monitor rejected: {payload['error']}")
                else:
                    _LOGGER.info(
                        f"SignalR Monitor accepted id={payload.get('invocationId')} "
                        "(void method: no subscription guarantee)"
                    )
                continue
            if msg_type == 7:
                _LOGGER.warning(
                    f"SignalR close frame error={payload.get('error') or 'none'}"
                )
                return
            if not target:
                continue
            if self._frames.get(kind) == 1:
                _LOGGER.info(f"SignalR first push target={target}")
            self._dashboard_diag["last_event"] = str(target)
            self._dashboard_diag["last_event_at"] = now_iso()
            args = _parse_hub_args(payload.get("arguments"))
            on_event = self._on_event
            if on_event is None:
                continue
            result = on_event(str(target), args)
            if asyncio.iscoroutine(result):
                await result
