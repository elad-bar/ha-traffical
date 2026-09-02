from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from engine.api_client import ApiClient, ApiError
from engine.consts import CLIENT_ID, OAUTH_SCOPE, OTP_TICKET_HEADER


class IdentityClient(ApiClient):
    def request_otp(self, phone: str, app_hash: str = "") -> tuple[str, Any]:
        resp = self.post_json(
            "/authorization/RequestOtp",
            {"Phone": phone, "AppHash": app_hash or ""},
            action="RequestOtp",
            debug_name="identity_request_otp",
        )
        ticket = resp.headers.get(OTP_TICKET_HEADER) or resp.headers.get("X-Otp-Ticket")
        if not ticket:
            raise ApiError("RequestOtp succeeded but x-otp-ticket header was missing.")
        body = resp.json() if resp.content else {}
        return ticket, body.get("expiredIn")

    def authorize(
        self,
        phone: str,
        otp: str,
        ticket: str,
        challenge: str,
        device_id: str,
    ) -> str:
        if not ticket:
            raise ApiError("No OTP ticket. Request a new OTP first.")
        resp = self.get(
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
            debug_name="identity_authorize",
        )
        data = resp.json()
        code = data.get("code") or ""
        if not code:
            raise ApiError(f"authorize returned no code: {data}")
        return code

    def exchange_code(self, code: str, verifier: str, retry_redirect: bool = True) -> dict[str, Any]:
        form = {
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
        }
        try:
            resp = self.post_form(
                "/connect/token",
                form,
                action="token",
                debug_name="identity_exchange_code",
            )
        except ApiError:
            if not retry_redirect:
                raise
            host = urlparse(self.base_url).netloc
            form["redirect_uri"] = f"com.shift://{host}/signin-callback"
            resp = self.post_form(
                "/connect/token",
                form,
                action="token",
                debug_name="identity_exchange_code_redirect",
            )
        return resp.json()

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        resp = self.post_form(
            "/connect/token",
            {
                "client_id": CLIENT_ID,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            action="token",
            debug_name="identity_refresh",
        )
        return resp.json()

    def userinfo(self) -> dict[str, Any]:
        try:
            resp = self.get(
                "/connect/userinfo",
                auth=True,
                action="userinfo",
                debug_name="identity_userinfo",
            )
        except ApiError as exc:
            if exc.status_code == 401:
                raise PermissionError("userinfo unauthorized") from exc
            raise
        return resp.json()
