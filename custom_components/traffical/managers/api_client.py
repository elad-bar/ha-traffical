"""Shared aiohttp REST client (HA-free)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
import logging
from typing import Any

import aiohttp

from ..common.consts import DEFAULT_LANGUAGE, HTTP_TIMEOUT
from ..common.helpers import authorization_header, now_iso
from ..models.exceptions import ApiError

_LOGGER = logging.getLogger(__name__)

REDACT_HEADER_KEYS = {"authorization", "x-otp-ticket"}
REDACT_BODY_KEYS = {
    "otp",
    "code",
    "code_verifier",
    "access_token",
    "refresh_token",
    "id_token",
}
REDACT_VALUE = "***"
_QUERY_SKIP_PATHS = frozenset({"/connect/authorize", "/connect/token"})
_STATUS_ONLY_ACTIONS = frozenset({"userinfo"})


def redact_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (headers or {}).items():
        out[key] = REDACT_VALUE if key.lower() in REDACT_HEADER_KEYS else value
    return out


def redact_mapping(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: (
                REDACT_VALUE
                if str(key).lower() in REDACT_BODY_KEYS
                else redact_mapping(value)
            )
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [redact_mapping(item) for item in obj]
    return obj


class ApiClient:
    def __init__(
        self,
        base_url: str,
        session: aiohttp.ClientSession,
        language: str = DEFAULT_LANGUAGE,
        tokens_provider: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.session = session
        self.language = language or DEFAULT_LANGUAGE
        self.tokens_provider = tokens_provider
        self.on_unauthorized: Callable[[], Awaitable[bool]] | None = None
        self._query_account: dict[str, dict[str, Any]] = {}
        self._query_rides: dict[str, dict[str, dict[str, Any]]] = {}

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def headers(
        self, extra: dict[str, str] | None = None, auth: bool = False
    ) -> dict[str, str]:
        out = {"Accept-Language": self.language, "lang": self.language}
        if extra:
            out.update(extra)
        if auth:
            tokens = self.tokens_provider() if self.tokens_provider else None
            if tokens and tokens.get("access_token"):
                out["Authorization"] = authorization_header(tokens)
        return out

    async def _read_text(self, resp: aiohttp.ClientResponse) -> str:
        return await resp.text()

    def _raise_for_status(self, status: int, action: str, body: str | None) -> None:
        if status >= 400:
            raise ApiError(
                f"{action} failed ({status})",
                status_code=status,
                body=body,
            )

    async def _retry_after_401(self, auth: bool, retried: bool, status: int) -> bool:
        if retried or not auth or status != 401:
            return False
        if self.on_unauthorized is None:
            return False
        return bool(await self.on_unauthorized())

    def _query_key(self, method: str, path: str, action: str | None) -> str:
        if action:
            return f"{method} {path} ({action})"
        return f"{method} {path}"

    def _response_shape(self, parsed: Any, action: str | None) -> Any:
        if action in _STATUS_ONLY_ACTIONS:
            return None
        if isinstance(parsed, list):
            return {"kind": "list", "count": len(parsed)}
        if isinstance(parsed, dict):
            shape: dict[str, Any] = {
                "kind": "object",
                "keys": sorted(str(key) for key in parsed),
            }
            if parsed.get("code") is not None:
                shape["code"] = parsed.get("code")
            if parsed.get("msg") is not None:
                shape["msg"] = parsed.get("msg")
            return shape
        if parsed is None:
            return None
        return {"kind": type(parsed).__name__}

    def _ride_ids_from(
        self, params: dict[str, Any] | None, json_body: Any
    ) -> list[int]:
        ids: list[int] = []

        def _add(raw: Any) -> None:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                return

        for src in (params, json_body if isinstance(json_body, dict) else None):
            if not src:
                continue
            raw = src.get("rideId")
            if raw is None:
                raw = src.get("ride_id")
            if raw is not None:
                _add(raw)
        if isinstance(json_body, list):
            for item in json_body:
                if isinstance(item, dict):
                    raw = item.get("rideId")
                    if raw is None:
                        raw = item.get("ride_id")
                    if raw is not None:
                        _add(raw)
                else:
                    _add(item)
        return ids

    def _record_query(
        self,
        *,
        method: str,
        path: str,
        action: str | None,
        started_at: str,
        finished_at: str,
        http_status: int | None,
        parsed: Any,
        error: str | None,
        params: dict[str, Any] | None,
        json_body: Any,
    ) -> None:
        if path in _QUERY_SKIP_PATHS:
            return
        record = {
            "request": {
                "started_at": started_at,
                "finished_at": finished_at,
                "http_status": http_status,
                "error": error,
            },
            "shape": self._response_shape(parsed, action),
        }
        key = self._query_key(method, path, action)
        ride_ids = self._ride_ids_from(params, json_body)
        if ride_ids:
            for ride_id in ride_ids:
                bucket = self._query_rides.setdefault(str(ride_id), {})
                bucket[key] = record
            return
        self._query_account[key] = record

    def query_log_for_diagnostics(
        self, ride_id: int | str | None = None
    ) -> dict[str, Any]:
        """Last sanitized HTTP snapshots for diagnostics (not logs)."""
        account = {k: dict(v) for k, v in self._query_account.items()}
        if ride_id is not None:
            rid = str(ride_id)
            per = self._query_rides.get(rid) or {}
            return {"account": account, "rides": {rid: dict(per)}}
        rides = {rid: dict(bucket) for rid, bucket in self._query_rides.items()}
        return {"account": account, "rides": rides}

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        form: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        auth: bool = False,
        action: str | None = None,
    ) -> Any:
        url = self.url(path)
        action_name = action or path
        retried = False
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        while True:
            headers = self.headers(extra_headers, auth=auth)
            if form is not None:
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            _LOGGER.debug(f"{method} {path}")
            started_at = now_iso()
            status: int | None = None
            parsed: Any = None
            try:
                async with self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=form,
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    status = resp.status
                    body_text = await self._read_text(resp)
                    if body_text:
                        try:
                            parsed = json.loads(body_text)
                        except ValueError:
                            parsed = body_text
                    else:
                        parsed = None
            except aiohttp.ClientError as exc:
                self._record_query(
                    method=method,
                    path=path,
                    action=action,
                    started_at=started_at,
                    finished_at=now_iso(),
                    http_status=status,
                    parsed=None,
                    error=str(exc),
                    params=params,
                    json_body=json_body,
                )
                raise ApiError(f"{action_name} failed: {exc}") from exc
            if await self._retry_after_401(auth, retried, status):
                retried = True
                continue
            error = None
            try:
                self._raise_for_status(status, action_name, body_text)
            except ApiError as exc:
                error = str(exc)
                self._record_query(
                    method=method,
                    path=path,
                    action=action,
                    started_at=started_at,
                    finished_at=now_iso(),
                    http_status=status,
                    parsed=parsed,
                    error=error,
                    params=params,
                    json_body=json_body,
                )
                raise
            self._record_query(
                method=method,
                path=path,
                action=action,
                started_at=started_at,
                finished_at=now_iso(),
                http_status=status,
                parsed=parsed,
                error=error,
                params=params,
                json_body=json_body,
            )
            return parsed

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        auth: bool = False,
        action: str | None = None,
    ) -> Any:
        return await self.request(
            "GET",
            path,
            params=params,
            extra_headers=extra_headers,
            auth=auth,
            action=action,
        )

    async def post_json(
        self,
        path: str,
        payload: Any,
        extra_headers: dict[str, str] | None = None,
        auth: bool = False,
        action: str | None = None,
    ) -> Any:
        return await self.request(
            "POST",
            path,
            json_body=payload,
            extra_headers=extra_headers,
            auth=auth,
            action=action,
        )

    async def put_json(
        self,
        path: str,
        payload: Any,
        extra_headers: dict[str, str] | None = None,
        auth: bool = False,
        action: str | None = None,
    ) -> Any:
        return await self.request(
            "PUT",
            path,
            json_body=payload,
            extra_headers=extra_headers,
            auth=auth,
            action=action,
        )

    async def post_form(
        self,
        path: str,
        form: dict[str, str],
        extra_headers: dict[str, str] | None = None,
        auth: bool = False,
        action: str | None = None,
    ) -> Any:
        return await self.request(
            "POST",
            path,
            form=form,
            extra_headers=extra_headers,
            auth=auth,
            action=action,
        )
