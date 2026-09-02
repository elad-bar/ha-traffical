"""HA-free REST / SignalR / store tests."""

from __future__ import annotations

import json

import pytest

from custom_components.traffical.common.helpers import create_pkce, mask_phone
from custom_components.traffical.managers.api_client import ApiClient
from custom_components.traffical.managers.identity_client import IdentityClient
from custom_components.traffical.managers.mobile_client import MobileClient
from custom_components.traffical.managers.signalr_client import _parse_hub_args
from custom_components.traffical.managers.store import SessionStore
from custom_components.traffical.models.rides import (
    ride_device_key,
    rides_customer_type,
    status_live,
)


def test_ride_device_key_stable() -> None:
    assert ride_device_key(392681, 120) == "392681:120"
    assert ride_device_key("x", 1) is None


def test_customer_type_municipality() -> None:
    assert rides_customer_type(28) == "Municipality"
    assert rides_customer_type(None) == "Municipality"


def test_status_live() -> None:
    assert status_live("OngoingMonitored")
    assert not status_live("New")


def test_pkce_and_mask() -> None:
    verifier, challenge = create_pkce()
    assert verifier
    assert challenge
    assert mask_phone("0501234567") == "***4567"


def test_parse_hub_json_string() -> None:
    parsed = _parse_hub_args(['{"stationId": 1}'])
    assert parsed == {"stationId": 1}


def test_store_tokens(tmp_path) -> None:
    store = SessionStore(tmp_path / "config.json")
    store.apply_environment("Live")
    store.set_tokens({"access_token": "a", "refresh_token": "r", "expires_in": 60})
    store.save()
    other = SessionStore(tmp_path / "config.json")
    other.load()
    assert other.tokens["access_token"] == "a"
    assert other.device_id


class _FakeResp:
    def __init__(self, status: int, payload: object, headers: dict | None = None) -> None:
        self.status = status
        self._payload = payload
        self.headers = headers or {}
        self.content_type = "application/json"

    async def text(self) -> str:
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)

    async def json(self, content_type=None):
        return self._payload

    async def read(self) -> bytes:
        return (await self.text()).encode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, resp: _FakeResp) -> None:
        self.resp = resp
        self.calls: list[tuple] = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.resp

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.resp


@pytest.mark.asyncio
async def test_identity_request_otp() -> None:
    resp = _FakeResp(200, {"expiredIn": 90}, headers={"x-otp-ticket": "ticket-1"})
    session = _FakeSession(resp)
    client = IdentityClient("https://id.example", session)  # type: ignore[arg-type]
    ticket, expired = await client.request_otp("0500000000")
    assert ticket == "ticket-1"
    assert expired == 90


@pytest.mark.asyncio
async def test_mobile_list_rides() -> None:
    resp = _FakeResp(200, [{"rideId": 1}])
    session = _FakeSession(resp)
    client = MobileClient("https://api.example", session)  # type: ignore[arg-type]
    data = await client.list_rides("Municipality", "2026-09-02")
    assert data == [{"rideId": 1}]
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert "Rides/Municipality" in url


@pytest.mark.asyncio
async def test_api_client_raises() -> None:
    resp = _FakeResp(500, "nope")
    session = _FakeSession(resp)
    client = ApiClient("https://api.example", session)  # type: ignore[arg-type]
    with pytest.raises(Exception):
        await client.get("/x", action="x")
