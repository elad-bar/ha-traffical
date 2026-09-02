"""Config flow for Traffical (stub)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .common.consts import DOMAIN

_LOGGER = logging.getLogger(__name__)

_STUB_UNIQUE_ID = "traffical"


class TrafficalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Placeholder config flow. Phone and OTP login land in Phase B."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user step."""
        if user_input is None:
            _LOGGER.info("config flow started step=user")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
            )

        await self.async_set_unique_id(_STUB_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        _LOGGER.info("config flow created entry title=Traffical")
        return self.async_create_entry(title="Traffical", data={})
