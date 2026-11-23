"""Adding Ryton Home Automations to Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class RytonConfigFlow(ConfigFlow, domain=DOMAIN):
    """There is nothing to fill in yet: confirming adds the integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Ryton Home Automations", data={})
        return self.async_show_form(step_id="user")
