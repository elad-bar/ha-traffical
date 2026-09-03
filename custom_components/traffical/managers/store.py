"""File-backed session store (HA-free)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import uuid

from ..common.consts import API_URL, CONFIG_PATH, DEFAULT_LANGUAGE, IDENTITY_URL
from ..common.helpers import now_iso


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_PATH
        self.data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            self.data = {}
            return self.data
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}
        return self.data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def clear(self) -> bool:
        self.data = {}
        if self.path.is_file():
            self.path.unlink()
            return True
        return False

    def apply_live_hosts(self) -> None:
        self.data["environment"] = "Live"
        self.data["api_url"] = API_URL
        self.data["identity_url"] = IDENTITY_URL
        self.data.setdefault("language", DEFAULT_LANGUAGE)
        self.data.setdefault("app_hash", "")
        if not self.data.get("device_id"):
            self.data["device_id"] = str(uuid.uuid4())

    def load_from_mapping(self, data: dict[str, Any]) -> None:
        self.data = dict(data)

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

    @property
    def child_id(self) -> str:
        return str(self.data.get("child_id") or "")

    def set_otp(self, ticket: str, expired_in: Any) -> None:
        self.data["otp_ticket"] = ticket
        self.data["otp_expired_in"] = expired_in
        self.data["otp_requested_at"] = now_iso()

    def clear_otp(self) -> None:
        self.data.pop("otp_ticket", None)
        self.data.pop("otp_expired_in", None)
        self.data.pop("otp_requested_at", None)

    def set_tokens(self, token_body: dict[str, Any]) -> None:
        previous = self.tokens
        self.data["tokens"] = {
            "access_token": token_body.get("access_token"),
            "refresh_token": token_body.get("refresh_token")
            or previous.get("refresh_token"),
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

    def persist_fields(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "api_url": self.api_url,
            "identity_url": self.identity_url,
            "language": self.language,
            "phone": self.phone,
            "device_id": self.device_id,
            "app_hash": self.app_hash,
            "tokens": self.tokens,
            "child_id": self.data.get("child_id"),
        }
