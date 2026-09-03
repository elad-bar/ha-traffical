"""Pure helpers (HA-free)."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import secrets
import socket
import ssl
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .consts import HTTP_TIMEOUT

_ISRAEL = ZoneInfo("Asia/Jerusalem")


def b64url_nopad(data: bytes) -> str:
    """Android Base64 flags 11: URL_SAFE | NO_WRAP | NO_PADDING."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def create_code_verifier() -> str:
    return b64url_nopad(secrets.token_bytes(32))


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("iso-8859-1")).digest()
    return b64url_nopad(digest)


def create_pkce() -> tuple[str, str]:
    verifier = create_code_verifier()
    return verifier, code_challenge(verifier)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def authorization_header(tokens: dict[str, Any]) -> str:
    token_type = (tokens.get("token_type") or "Bearer").strip()
    return f"{token_type} {tokens['access_token']}"


def partial_id(value: Any, keep: int = 8) -> str:
    text = str(value or "")
    if len(text) <= keep:
        return text
    return text[:keep]


def mask_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


def ssl_context() -> ssl.SSLContext:
    """Verify TLS, but drop VERIFY_X509_STRICT (Mashcal intermediates lack AKID)."""
    ctx = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def client_session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=ssl_context())
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    return aiohttp.ClientSession(connector=connector, timeout=timeout)


def entity_object_id(
    key: str, ride_key: str | None = None, station_id: str | None = None
) -> str:
    """Stable HA object id from catalog key and route/station ids, not names."""
    parts = ["traffical"]
    if ride_key:
        parts.append(str(ride_key).replace(":", "_"))
    parts.append(key)
    if station_id:
        parts.append(str(station_id))
    return "_".join(parts)


def parse_utc(value: Any) -> datetime | None:
    """Parse an API timestamp to UTC.

    Strings with ``Z`` or an offset keep that zone. Naive Mashcal ride times
    are Israel local (``Asia/Jerusalem``), not UTC.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_ISRAEL)
    return dt.astimezone(timezone.utc)
