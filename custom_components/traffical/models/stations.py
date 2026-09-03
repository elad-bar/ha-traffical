"""Ride station shape (HA-free, no I/O)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..common.helpers import parse_utc


def station_event_id(payload: Any) -> str | None:
    """Return a station ID from a SignalR station-arrival payload.

    The hub sends ``StationId``; REST station objects use ``stationId``.
    """
    if not isinstance(payload, dict):
        return str(payload) if payload is not None else None
    raw = payload.get("StationId")
    if raw is None:
        raw = payload.get("stationId")
    return str(raw) if raw is not None else None


class Station:
    """One stop on a ride path."""

    def __init__(self, payload: Any) -> None:
        self._raw = payload if isinstance(payload, dict) else {}

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    @property
    def station_id(self) -> str | None:
        raw = self._raw.get("stationId") or self._raw.get("id")
        return str(raw) if raw is not None else None

    @property
    def name(self) -> str:
        return str(self._raw.get("name") or self._raw.get("stationName") or "").strip()

    @property
    def address(self) -> str:
        return str(self._raw.get("address") or "").strip()

    @property
    def is_target(self) -> bool:
        return bool(self._raw.get("isTarget"))

    @property
    def label(self) -> str:
        """Display text: school/activity stops read better by name, stops by address."""
        if self.is_target:
            return self.name or self.address
        return self.address or self.name

    @property
    def arrived(self) -> bool:
        return self._raw.get("actualArriveDateTime") is not None

    @property
    def arrival_time(self) -> datetime | None:
        return parse_utc(self._raw.get("arrivalTime"))

    @property
    def actual_arrival(self) -> datetime | None:
        return parse_utc(self._raw.get("actualArriveDateTime"))

    @property
    def lat(self) -> float | None:
        return self._coord("lat")

    @property
    def lng(self) -> float | None:
        return self._coord("lng")

    def _coord(self, key: str) -> float | None:
        try:
            return float(self._raw.get(key))
        except (TypeError, ValueError):
            return None

    def has_passenger(self, member_id: int | None) -> bool:
        """Whether ``passengers[]`` lists this member."""
        if member_id is None:
            return False
        passengers = self._raw.get("passengers") or []
        if not isinstance(passengers, list):
            return False
        for passenger in passengers:
            if not isinstance(passenger, dict):
                continue
            try:
                if int(passenger.get("id")) == member_id:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def is_yours(self, passenger_stop: str, member_id: int | None) -> bool:
        """Whether this stop is the passenger's own, by name or assignment."""
        if passenger_stop and self.name == passenger_stop.strip():
            return True
        return self.has_passenger(member_id)
