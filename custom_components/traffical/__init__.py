"""The Traffical Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .common.consts import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = []

__all__ = [
    "DOMAIN",
    "PLATFORMS",
    "async_setup_entry",
    "async_unload_entry",
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Traffical from a config entry."""
    suffix = (
        " (existing entry)" if getattr(entry, "runtime_data", None) is not None else ""
    )
    _LOGGER.info(f"setup entry entry_id={entry.entry_id[:8]}{suffix}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info(f"unload entry entry_id={entry.entry_id[:8]}")
    return True
