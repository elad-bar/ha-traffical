from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timezone
from typing import Any

from engine.consts import DEBUG_DIR


def _configure_logging() -> None:
    raw = (os.environ.get("TRAFFICAL_LOG_LEVEL") or "").strip().upper()
    if raw:
        level = getattr(logging, raw, logging.INFO)
    else:
        debug = str(os.environ.get("DEBUG", "")).lower() == "true"
        level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(threadName)s[%(thread)d] %(levelname)s %(name)s %(message)s"
        )
    )
    root.addHandler(handler)
    for name in ("urllib3", "requests", "signalrcore", "websocket"):
        logging.getLogger(name).setLevel(logging.WARNING)


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


def write_debug_json(name: str, payload: dict[str, Any]) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def prompt(message: str) -> str:
    try:
        return input(message).strip()
    except EOFError:
        raise SystemExit("No input.") from None


def authorization_header(tokens: dict[str, Any]) -> str:
    token_type = (tokens.get("token_type") or "Bearer").strip()
    return f"{token_type} {tokens['access_token']}"
