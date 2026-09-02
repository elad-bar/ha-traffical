"""Identity / OTP / token client (HA-free)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from ..common.consts import CLIENT_ID, OAUTH_SCOPE, OTP_TICKET_HEADER
from ..models.exceptions import ApiError, AuthError
from .api_client import ApiClient


class IdentityClient(ApiClient):
    async def request_otp(self, phone: str, app_hash: str = "") -> tuple[str, Any]:
        url = self.url("/authorization/RequestOtp")
        headers = self.headers()
        payload = {"Phone": phone, "AppHash": app_hash or ""}
        async with self.session.post(url, json=payload, headers=headers) as resp:
            ticket = resp.headers.get(OTP_TICKET_HEADER) or resp.headers.get(
                "X-Otp-Ticket"
            )
            text = await resp.text()
            if resp.status >= 400:
                raise AuthError(
                    f"RequestOtp failed ({resp.status})",
                    status_code=resp.status,
                )
            body: Any = json.loads(text) if text else {}
        if not ticket:
            raise ApiError("RequestOtp succeeded but x-otp-ticket header was missing.")
        if not isinstance(body, dict):
            body = {}
        return ticket, body.get("expiredIn")

    async def authorize(
        self,
        phone: str,
        otp: str,
        ticket: str,
        challenge: str,
        device_id: str,
    ) -> str:
        if not ticket:
            raise ApiError("No OTP ticket. Request a new OTP first.")
        data = await self.get(
            "/connect/authorize",
            params={
                "client_id": CLIENT_ID,
                "response_type": "code",
                "scope": OAUTH_SCOPE,
                "response_mode": "body",
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "phone": phone,
                "otp": otp,
                "device_id": device_id,
            },
            extra_headers={OTP_TICKET_HEADER: ticket},
            action="authorize",
        )
        if not isinstance(data, dict):
            raise AuthError("authorize returned no code")
        code = data.get("code") or ""
        if not code:
            raise AuthError("authorize returned no code")
        return code

    async def exchange_code(
        self, code: str, verifier: str, retry_redirect: bool = True
    ) -> dict[str, Any]:
        form = {
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
        }
        try:
            data = await self.post_form(
                "/connect/token",
                form,
                action="token",
            )
        except ApiError:
            if not retry_redirect:
                raise
            host = urlparse(self.base_url).netloc
            form["redirect_uri"] = f"com.shift://{host}/signin-callback"
            data = await self.post_form(
                "/connect/token",
                form,
                action="token",
            )
        if not isinstance(data, dict):
            raise AuthError("token exchange returned no tokens")
        return data

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        data = await self.post_form(
            "/connect/token",
            {
                "client_id": CLIENT_ID,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            action="token",
        )
        if not isinstance(data, dict):
            raise AuthError("refresh returned no tokens")
        return data

    async def switch_child(self, child_id: str, refresh_token: str) -> dict[str, Any]:
        data = await self.post_form(
            "/connect/token",
            {
                "client_id": CLIENT_ID,
                "refresh_token": refresh_token,
                "grant_type": "switch_child",
                "child_id": str(child_id),
            },
            action="switch_child",
        )
        if not isinstance(data, dict):
            raise AuthError("switch_child returned no tokens")
        return data

    async def userinfo(self) -> dict[str, Any]:
        try:
            data = await self.get(
                "/connect/userinfo",
                auth=True,
                action="userinfo",
            )
        except ApiError as exc:
            if exc.status_code == 401:
                raise PermissionError("userinfo unauthorized") from exc
            raise
        if not isinstance(data, dict):
            return {}
        return data
