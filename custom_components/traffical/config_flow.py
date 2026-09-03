"""Config flow for Traffical."""

from __future__ import annotations

import logging
from typing import Any
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .common.consts import (
    CONF_POLL_INTERVAL,
    DOMAIN,
)
from .common.helpers import client_session, create_pkce, mask_phone
from .managers.identity_client import IdentityClient
from .managers.store import SessionStore
from .models.exceptions import ApiError, AuthError

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                "phone", default=defaults.get("phone", "")
            ): selector.TextSelector(),
        }
    )


def _otp_schema() -> vol.Schema:
    return vol.Schema({vol.Required("otp"): selector.TextSelector()})


class TrafficalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Phone + OTP login."""

    VERSION = 1

    def __init__(self) -> None:
        self._store = SessionStore()
        self._otp_ticket: str | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            _LOGGER.info("config flow started step=user")
            return self.async_show_form(step_id="user", data_schema=_user_schema())

        phone = str(user_input["phone"]).strip()
        self._store.apply_live_hosts()
        self._store.phone = phone
        if not self._store.device_id:
            self._store.data["device_id"] = str(uuid.uuid4())
        _LOGGER.info(f"config flow submit step=user env=Live phone={mask_phone(phone)}")
        try:
            await self._request_otp()
        except AuthError:
            _LOGGER.warning("config flow failed step=user error=invalid_auth")
            errors["base"] = "invalid_auth"
            return self.async_show_form(
                step_id="user", data_schema=_user_schema(user_input), errors=errors
            )
        except ApiError:
            _LOGGER.warning("config flow failed step=user error=cannot_connect")
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="user", data_schema=_user_schema(user_input), errors=errors
            )
        return await self.async_step_otp()

    async def _request_otp(self) -> None:
        _LOGGER.debug("_validate_login → IdentityClient.request_otp")
        session = client_session()
        try:
            identity = IdentityClient(
                self._store.identity_url, session, language=self._store.language
            )
            ticket, expired_in = await identity.request_otp(
                self._store.phone, self._store.app_hash
            )
        finally:
            await session.close()
        self._otp_ticket = ticket
        self._store.set_otp(ticket, expired_in)
        _LOGGER.info("otp requested")

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(step_id="otp", data_schema=_otp_schema())
        otp = str(user_input["otp"]).strip()
        try:
            tokens, user = await self._exchange_otp(otp)
        except AuthError:
            _LOGGER.warning("config flow failed step=otp error=invalid_auth")
            errors["base"] = "invalid_auth"
            return self.async_show_form(
                step_id="otp", data_schema=_otp_schema(), errors=errors
            )
        except ApiError:
            _LOGGER.warning("config flow failed step=otp error=cannot_connect")
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="otp", data_schema=_otp_schema(), errors=errors
            )
        self._store.set_tokens(tokens)
        self._store.set_user(user)
        unique = str(user.get("sub") or self._store.phone)
        await self.async_set_unique_id(unique)
        self._abort_if_unique_id_configured()
        title = (user.get("customer") or {}).get("name") or "Traffical"
        _LOGGER.info("config flow created entry title=Traffical")
        return self.async_create_entry(
            title=f"Traffical · {title}",
            data=self._store.persist_fields(),
        )

    async def _exchange_otp(self, otp: str) -> tuple[dict[str, Any], dict[str, Any]]:
        _LOGGER.debug("_validate_login → IdentityClient.verify_otp")
        verifier, challenge = create_pkce()
        session = client_session()
        try:
            identity = IdentityClient(
                self._store.identity_url, session, language=self._store.language
            )
            code = await identity.authorize(
                self._store.phone,
                otp,
                self._otp_ticket or "",
                challenge,
                self._store.device_id,
            )
            tokens = await identity.exchange_code(code, verifier)
            identity.tokens_provider = lambda: tokens
            user = await identity.userinfo()
        finally:
            await session.close()
        _LOGGER.info("login ok")
        return tokens, user

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if self._reauth_entry is None:
            return self.async_abort(reason="already_configured")
        self._store.load_from_mapping(dict(self._reauth_entry.data))
        try:
            await self._request_otp()
        except (ApiError, AuthError):
            _LOGGER.warning("config flow failed step=reauth error=cannot_connect")
            return self.async_abort(reason="cannot_connect")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=_otp_schema(),
                description_placeholders={"phone": mask_phone(self._store.phone)},
            )
        otp = str(user_input["otp"]).strip()
        try:
            tokens, user = await self._exchange_otp(otp)
        except AuthError:
            errors["base"] = "invalid_auth"
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=_otp_schema(),
                errors=errors,
                description_placeholders={"phone": mask_phone(self._store.phone)},
            )
        except ApiError:
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=_otp_schema(),
                errors=errors,
                description_placeholders={"phone": mask_phone(self._store.phone)},
            )
        self._store.set_tokens(tokens)
        self._store.set_user(user)
        assert self._reauth_entry is not None
        _LOGGER.info("config flow reauth success")
        return self.async_update_reload_and_abort(
            self._reauth_entry, data=self._store.persist_fields()
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return TrafficalOptionsFlow(config_entry)


class TrafficalOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = int(self._entry.options.get(CONF_POLL_INTERVAL, 180))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POLL_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=30, max=600)
                    )
                }
            ),
        )
