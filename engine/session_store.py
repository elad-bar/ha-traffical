from __future__ import annotations

import json
import uuid
from typing import Any

from engine.consts import CONFIG_PATH, DATA_DIR, DEFAULT_LANGUAGE, ENVIRONMENTS
from engine.helpers import now_iso


class SessionStore:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        if not CONFIG_PATH.is_file():
            self.data = {}
            return self.data
        try:
            self.data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}
        return self.data

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def clear(self) -> bool:
        self.data = {}
        if CONFIG_PATH.is_file():
            CONFIG_PATH.unlink()
            return True
        return False

    def apply_environment(self, env_name: str) -> None:
        env = ENVIRONMENTS[env_name]
        self.data["environment"] = env_name
        self.data["api_url"] = env["api_url"]
        self.data["identity_url"] = env["identity_url"]
        self.data.setdefault("language", DEFAULT_LANGUAGE)
        self.data.setdefault("app_hash", "")
        if not self.data.get("device_id"):
            self.data["device_id"] = str(uuid.uuid4())

    @property
    def phone(self) -> str:
        return self.data.get("phone") or ""

    @phone.setter
    def phone(self, value: str) -> None:
        self.data["phone"] = value

    @property
    def tokens(self) -> dict[str, Any]:
        return self.data.get("tokens") or {}

    @property
    def otp_ticket(self) -> str:
        return self.data.get("otp_ticket") or ""

    @property
    def user(self) -> dict[str, Any]:
        return self.data.get("user") or {}

    @property
    def identity_url(self) -> str:
        return self.data.get("identity_url") or ""

    @property
    def api_url(self) -> str:
        return self.data.get("api_url") or ""

    @property
    def language(self) -> str:
        return self.data.get("language") or DEFAULT_LANGUAGE

    @property
    def environment(self) -> str:
        return self.data.get("environment") or ""

    @property
    def device_id(self) -> str:
        return self.data.get("device_id") or ""

    @property
    def app_hash(self) -> str:
        return self.data.get("app_hash") or ""

    def set_otp(self, ticket: str, expired_in: Any) -> None:
        self.data["otp_ticket"] = ticket
        self.data["otp_expired_in"] = expired_in
        self.data["otp_requested_at"] = now_iso()

    def clear_otp(self) -> None:
        self.data.pop("otp_ticket", None)
        self.data.pop("otp_expired_in", None)
        self.data.pop("otp_requested_at", None)

    def set_tokens(self, token_body: dict[str, Any]) -> None:
        self.data["tokens"] = {
            "access_token": token_body.get("access_token"),
            "refresh_token": token_body.get("refresh_token"),
            "id_token": token_body.get("id_token"),
            "token_type": token_body.get("token_type") or "Bearer",
            "expires_in": token_body.get("expires_in"),
            "scope": token_body.get("scope"),
            "obtained_at": now_iso(),
        }

    def clear_tokens(self) -> None:
        self.data.pop("tokens", None)

    def set_user(self, user: dict[str, Any]) -> None:
        self.data["user"] = user

    def set_roles(self, roles: Any) -> None:
        self.data["roles"] = roles

    def set_policies(self, policies: Any) -> None:
        self.data["policies"] = policies
