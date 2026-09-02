"""Entity keys for platforms."""

from __future__ import annotations

HUB_SENSORS = ("next_ride",)
HUB_BINARY = ("session",)
HUB_BUTTONS = ("refresh",)
RIDE_SENSORS = ("status", "my_station", "destination", "driver", "vehicle")
RIDE_BINARY = ("checked_in",)
RIDE_BUTTONS = ("check_in", "check_out", "not_coming")
