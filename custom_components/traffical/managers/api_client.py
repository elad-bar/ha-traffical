"""Shared aiohttp REST client (HA-free)."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from ..common.consts import DEFAULT_LANGUAGE, HTTP_TIMEOUT
from ..common.helpers import authorization_header
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

    def _raise_for_status(
        self, status: int, action: str, body: str | None
    ) -> None:
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
                headers.setdefault(
                    "Content-Type", "application/x-www-form-urlencoded"
                )
            _LOGGER.debug(f"{method} {path}")
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
                    parsed: Any
                    if body_text:
                        try:
                            parsed = json.loads(body_text)
                        except ValueError:
                            parsed = body_text
                    else:
                        parsed = None
            except aiohttp.ClientError as exc:
                raise ApiError(f"{action_name} failed: {exc}") from exc
            if await self._retry_after_401(auth, retried, status):
                retried = True
                continue
            self._raise_for_status(status, action_name, body_text)
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
