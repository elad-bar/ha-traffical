#!/usr/bin/env python3
"""Console login client for Traffical / Shift identity.

Session is stored in data/config.json at the repo root:
  - phone saved after RequestOtp  → next run starts at the OTP step
  - tokens saved after a successful OTP  → next run is treated as logged in

Usage:
  python engine/entrypoint.py
  python -m engine.entrypoint
  python engine/entrypoint.py --clean
  python engine/entrypoint.py --env Live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.app import App
from engine.consts import DEFAULT_LANGUAGE, ENVIRONMENTS
from engine.helpers import _configure_logging
from engine.identity_client import IdentityClient
from engine.mobile_client import MobileClient
from engine.session_store import SessionStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Traffical / Shift console login")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete data/config.json and start from the phone prompt",
    )
    parser.add_argument(
        "--env",
        choices=list(ENVIRONMENTS),
        help="Environment for a new session (default: Live). Ignored if a session already exists unless --clean.",
    )
    return parser.parse_args()


def main() -> int:
    _configure_logging()
    args = parse_args()
    store = SessionStore()
    identity = IdentityClient(
        base_url="",
        language=DEFAULT_LANGUAGE,
        tokens_provider=lambda: store.tokens,
    )
    mobile = MobileClient(
        base_url="",
        language=DEFAULT_LANGUAGE,
        tokens_provider=lambda: store.tokens,
    )
    return App(store, identity, mobile).run(clean=args.clean, env=args.env)


if __name__ == "__main__":
    sys.exit(main())
