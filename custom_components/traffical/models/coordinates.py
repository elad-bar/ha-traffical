"""Monitoring-path coordinate shapes (HA-free, no I/O)."""

from __future__ import annotations

from typing import Any

from ..common.helpers import partial_id

# Car, driver, and accompany build the vehicle trail on the Traffical map;
# passenger and supervisor positions are other people, not the bus.
_BUS_SOURCE_TYPES = frozenset({1, 2, 4})


def coord_from_payload(payload: Any) -> tuple[float | None, float | None]:
    """Read a lat/lng pair from a REST or SignalR point, whatever the casing."""
    if not isinstance(payload, dict):
        return None, None
    lat = payload.get("latitude")
    if lat is None:
        lat = payload.get("lat")
    if lat is None:
        lat = payload.get("Latitude")
    lng = payload.get("longitude")
    if lng is None:
        lng = payload.get("lng")
    if lng is None:
        lng = payload.get("Longitude")
    try:
        lat_f = float(lat) if lat is not None else None
        lng_f = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        return None, None
    return lat_f, lng_f


class MonitoredPath:
    """A ride's uploaded positions, flat live pushes or grouped REST snapshots."""

    def __init__(self, payload: Any) -> None:
        self._items = payload if isinstance(payload, list) else [payload]

    @property
    def points(self) -> list[dict[str, Any]]:
        """Bus positions in upload order, with non-vehicle sources dropped."""
        points: list[dict[str, Any]] = []
        for item in self._items:
            if not isinstance(item, dict) or not self._is_bus(item):
                continue
            nested = self._nested(item)
            if nested is None:
                if self._has_coord(item):
                    points.append(item)
                continue
            for point in nested:
                if isinstance(point, dict) and self._has_coord(point):
                    points.append(point)
        return points

    @property
    def latest(self) -> dict[str, Any] | None:
        points = self.points
        return points[-1] if points else None

    @property
    def sources(self) -> list[str]:
        """Each group as ``sourceType:member:count``, for diagnosing who uploads."""
        out: list[str] = []
        for item in self._items:
            if not isinstance(item, dict):
                continue
            source = item.get("SourceType")
            if source is None:
                source = item.get("sourceType")
            member = item.get("MemberId")
            if member is None:
                member = item.get("memberId")
            nested = self._nested(item)
            count = len(nested) if nested is not None else 1
            out.append(f"{source}:{partial_id(member)}:{count}")
        return out

    @staticmethod
    def _nested(item: dict[str, Any]) -> list[Any] | None:
        nested = item.get("Coordinates")
        if nested is None:
            nested = item.get("coordinates")
        if nested is None:
            return None
        return nested if isinstance(nested, list) else [nested]

    @staticmethod
    def _is_bus(item: dict[str, Any]) -> bool:
        source = item.get("SourceType")
        if source is None:
            source = item.get("sourceType")
        if source is None:
            return True
        try:
            return int(source) in _BUS_SOURCE_TYPES
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _has_coord(point: dict[str, Any]) -> bool:
        return all(value is not None for value in coord_from_payload(point))
