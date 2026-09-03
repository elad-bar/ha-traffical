"""Ride-device calendar (today plus the next listed day)."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common.base_entity import TrafficalEntity
from .common.entity_setup import async_setup_entities
from .managers.coordinator import TrafficalCoordinator
from .models.ride_calendar import (
    RideCalendarItem,
    current_event,
    events_for_line,
)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TrafficalCoordinator = entry.runtime_data
    async_setup_entities(
        hass, entry, coordinator, "calendar", async_add_entities, TrafficalCalendar
    )


class TrafficalCalendar(TrafficalEntity, CalendarEntity):
    @property
    def event(self) -> CalendarEvent | None:
        item = current_event(
            (self.coordinator.data or {}).get("occurrences") or [],
            self.ride_key or "",
            date.today(),
            member_id=self.coordinator.member_id(),
        )
        return _ha_event(item) if item is not None else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        return [
            _ha_event(item)
            for item in events_for_line(
                (self.coordinator.data or {}).get("occurrences") or [],
                self.ride_key or "",
                start_date,
                end_date,
                member_id=self.coordinator.member_id(),
            )
        ]


def _ha_event(item: RideCalendarItem) -> CalendarEvent:
    return CalendarEvent(
        start=item.start,
        end=item.end,
        summary=item.summary,
        description=item.description,
        location=item.location,
        uid=item.uid,
    )
