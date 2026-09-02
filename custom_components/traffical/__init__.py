"""The Traffical Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .common.consts import DOMAIN, PLATFORMS as _PLATFORM_NAMES
from .common.helpers import partial_id
from .managers.coordinator import TrafficalCoordinator, async_create_coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform(p) for p in _PLATFORM_NAMES]

type TrafficalConfigEntry = ConfigEntry[TrafficalCoordinator]

__all__ = [
    "DOMAIN",
    "PLATFORMS",
    "async_setup_entry",
    "async_unload_entry",
]


async def async_setup_entry(hass: HomeAssistant, entry: TrafficalConfigEntry) -> bool:
    """Set up Traffical from a config entry."""
    suffix = (
        " (existing entry)" if getattr(entry, "runtime_data", None) is not None else ""
    )
    _LOGGER.info(f"setup entry entry_id={partial_id(entry.entry_id)}{suffix}")
    coordinator = await async_create_coordinator(hass, entry)
    try:
        await coordinator.async_start()
    except ConfigEntryAuthFailed:
        await coordinator.async_stop()
        _LOGGER.error(f"setup auth failed entry_id={partial_id(entry.entry_id)}")
        raise
    except Exception as err:
        await coordinator.async_stop()
        _LOGGER.exception("Traffical setup failed")
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from err

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    _LOGGER.debug(f"async_forward_entry_setups platforms={len(PLATFORMS)}")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info(f"platforms setup complete count={len(PLATFORMS)}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrafficalConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info(
        f"unload entry entry_id={partial_id(entry.entry_id)} domains={len(PLATFORMS)}"
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _LOGGER.info(f"unload platforms ok={unload_ok}")
    coordinator = entry.runtime_data
    await coordinator.async_stop()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: TrafficalConfigEntry) -> None:
    """Reload when options or entry data change."""
    _LOGGER.info(
        f"reload entry entry_id={partial_id(entry.entry_id)} reason=update_listener"
    )
    await hass.config_entries.async_reload(entry.entry_id)
