"""Ride occurrence window (HA-free, no I/O)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..common.consts import RIDES_LOOKAHEAD_DAYS
from .rides import Ride, focus_ride_key, status_finished, status_live


class RideWindow:
    """Dated ride occurrences plus the line devices bound to today.

    An occurrence is one instance of a line on one service date. Line devices
    (``routeId:direction``) bind to **today** only, so a finished trip keeps its
    status until the calendar date rolls, while ``focus`` may already point at a
    later day. The caller performs the HTTP listing and hands rows to
    :meth:`set_day`; lookahead days are listed only until a next ride is found.
    """

    def __init__(self, lookahead_days: int = RIDES_LOOKAHEAD_DAYS) -> None:
        self.lookahead_days = lookahead_days
        self.today: date | None = None
        self.occurrences: list[dict[str, Any]] = []
        self.loaded_dates: set[str] = set()
        self.rides: dict[str, dict[str, Any]] = {}

    @property
    def today_iso(self) -> str:
        return self.today.isoformat() if self.today is not None else ""

    def start_day(self, today: date) -> None:
        """Make ``today`` the active day and forget earlier dates."""
        self.today = today
        today_iso = today.isoformat()
        self.occurrences = [
            occ for occ in self.occurrences if self._service_date(occ) >= today_iso
        ]
        self.loaded_dates = {day for day in self.loaded_dates if day >= today_iso}

    def dates(self) -> list[date]:
        """Today through today plus the lookahead cap."""
        start = self.today if self.today is not None else date.today()
        return [
            start + timedelta(days=offset) for offset in range(self.lookahead_days + 1)
        ]

    def overlapping_dates(
        self, change_from: date | None, change_to: date | None
    ) -> set[str]:
        """Dates in range that this window cares about."""
        if change_from is None or change_to is None:
            return set()
        return {
            day.isoformat() for day in self.dates() if change_from <= day <= change_to
        }

    def needs_today(self, force_dates: set[str] | None = None) -> bool:
        """List today while it still has an unfinished ride, or once per day."""
        today_iso = self.today_iso
        if not today_iso:
            return False
        if today_iso in (force_dates or set()):
            return True
        if today_iso not in self.loaded_dates:
            return True
        return any(
            not status_finished(str(occ.get("status") or ""))
            for occ in self.occurrences
            if self._service_date(occ) == today_iso
        )

    def next_missing_date(self) -> date | None:
        """Next lookahead day that was never listed, within the cap."""
        for day in self.dates()[1:]:
            if day.isoformat() not in self.loaded_dates:
                return day
        return None

    def forced_days(self, force_dates: set[str]) -> list[date]:
        """Cached days a route change invalidated."""
        return [day for day in self.dates() if day.isoformat() in force_dates]

    def set_day(
        self, service_date: str, entries: Iterable[tuple[Any, Any, Any]]
    ) -> None:
        """Replace one service date with freshly listed ``(row, details, checkin)``."""
        kept = [
            occ for occ in self.occurrences if self._service_date(occ) != service_date
        ]
        listed: list[dict[str, Any]] = []
        for list_row, details, checkin in entries:
            occ = Ride(list_row, details).occurrence(service_date, checkin)
            if occ is not None:
                listed.append(occ)
        self.occurrences = kept + listed
        self.loaded_dates.add(service_date)

    @property
    def focus(self) -> dict[str, Any] | None:
        """Live occurrence, else the earliest unfinished one by date and start."""
        live = [
            occ for occ in self.occurrences if status_live(str(occ.get("status") or ""))
        ]
        if live:
            return min(live, key=self._sort_key)
        upcoming = [
            occ
            for occ in self.occurrences
            if not status_finished(str(occ.get("status") or ""))
        ]
        if not upcoming:
            return None
        return min(upcoming, key=self._sort_key)

    @property
    def live_key(self) -> str | None:
        for key, ride in self.rides.items():
            if ride.get("assigned_today") and status_live(
                str(ride.get("status") or "")
            ):
                return key
        return None

    @property
    def map_focus_key(self) -> str | None:
        """Bound ride for map pins and GPS. Never a future-day occurrence."""
        return focus_ride_key(self.rides)

    def bind(self) -> dict[str, dict[str, Any]]:
        """Rebuild the line devices from the cached occurrences."""
        previous = self.rides
        rides: dict[str, dict[str, Any]] = {
            key: dict(ride) for key, ride in previous.items()
        }
        for ride in rides.values():
            ride["assigned_today"] = False
        for key, line in self._by_line().items():
            bound = self._bind_line(previous.get(key), line)
            if bound is not None:
                rides[key] = bound
        self.rides = rides
        return rides

    def occurrence_for(self, ride_id: int) -> dict[str, Any] | None:
        for occ in self.occurrences:
            if self._same_ride(occ, ride_id):
                return occ
        return None

    def bound_for(self, ride_id: int) -> tuple[str, dict[str, Any]] | None:
        for key, ride in self.rides.items():
            if ride.get("assigned_today") and self._same_ride(ride, ride_id):
                return key, ride
        return None

    def apply_status(self, ride_id: int, status: str) -> tuple[str | None, str] | None:
        """Patch a streamed status. Returns ``(bound key, previous status)``."""
        occ = self.occurrence_for(ride_id)
        bound = self.bound_for(ride_id)
        if occ is None and bound is None:
            return None
        source = bound[1] if bound is not None else occ
        previous_status = str((source or {}).get("status") or "")
        if occ is not None:
            self._patch_status(occ, status)
        if bound is not None:
            self._patch_status(bound[1], status)
        return (bound[0] if bound is not None else None), previous_status

    def _patch_status(self, cached: dict[str, Any], status: str) -> None:
        cached["status"] = status
        row = cached.get("list_row")
        if isinstance(row, dict):
            row["status"] = status
        details = cached.get("details")
        if isinstance(details, dict):
            details["status"] = status

    def _bind_line(
        self, previous: dict[str, Any] | None, line: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        today_iso = self.today_iso
        today_rows = [occ for occ in line if self._service_date(occ) == today_iso]
        if not today_rows:
            return None
        unfinished = [
            occ
            for occ in today_rows
            if not status_finished(str(occ.get("status") or ""))
        ]
        bound = dict(unfinished[0] if unfinished else today_rows[0])
        bound["assigned_today"] = True
        prior = previous if isinstance(previous, dict) else {}
        same_ride = prior.get("ride_id") == bound.get("ride_id")
        bound["lat"] = prior.get("lat") if same_ride else None
        bound["lng"] = prior.get("lng") if same_ride else None
        bound["passed_stations"] = (
            set(prior.get("passed_stations") or []) if same_ride else set()
        )
        bound["approaching_fired"] = (
            bool(prior.get("approaching_fired")) if same_ride else False
        )
        return bound

    def _by_line(self) -> dict[str, list[dict[str, Any]]]:
        lines: dict[str, list[dict[str, Any]]] = {}
        for occ in self.occurrences:
            lines.setdefault(str(occ.get("key") or ""), []).append(occ)
        return lines

    def _sort_key(self, occ: dict[str, Any]) -> tuple[str, datetime]:
        far = datetime(9999, 12, 31, tzinfo=timezone.utc)
        return (self._service_date(occ), Ride.from_cache(occ).start or far)

    def _service_date(self, occ: dict[str, Any]) -> str:
        return str(occ.get("service_date") or "")

    def _same_ride(self, cached: dict[str, Any], ride_id: int) -> bool:
        cached_id = cached.get("ride_id")
        if cached_id is None:
            return False
        try:
            return int(cached_id) == ride_id
        except (TypeError, ValueError):
            return False
