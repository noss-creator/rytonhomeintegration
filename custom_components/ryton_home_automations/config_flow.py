"""Adding Ryton Home Automations to Home Assistant, and pairing it with the website."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_HOUSE_ID,
    CONF_HOUSE_KEY,
    CONF_HOUSE_NAME,
    CONF_PAIRING_CODE,
    DOMAIN,
)
from .website import WebsiteError, WebsiteRefused, async_pair

# The pairing code may be left empty: a house with no internet runs from a
# schedule file and is never paired.
SCHEMA = vol.Schema({vol.Optional(CONF_PAIRING_CODE, default=""): str})


class RytonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the integration, with a pairing code from the website if there is one."""

    VERSION = 1

    async def _async_pair(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> dict[str, Any] | None:
        """Return the house's details from pairing, {} if no code was given, or None on failure."""
        code = user_input.get(CONF_PAIRING_CODE, "").strip()
        if not code:
            return {}
        try:
            answer = await async_pair(self.hass, code)
        except WebsiteRefused:
            errors["base"] = "invalid_pairing_code"
            return None
        except WebsiteError:
            errors["base"] = "cannot_connect"
            return None
        return {
            CONF_HOUSE_ID: answer["house_id"],
            CONF_HOUSE_NAME: answer.get("house_name") or "",
            CONF_HOUSE_KEY: answer["house_key"],
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = await self._async_pair(user_input, errors)
            if data is not None:
                return self.async_create_entry(title="Ryton Home Automations", data=data)
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair a house that is already added, or pair it again."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = await self._async_pair(user_input, errors)
            if data == {}:
                errors["base"] = "pairing_code_needed"
            elif data is not None:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data=data
                )
        return self.async_show_form(step_id="reconfigure", data_schema=SCHEMA, errors=errors)
