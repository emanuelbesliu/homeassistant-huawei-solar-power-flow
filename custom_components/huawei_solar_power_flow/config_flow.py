"""Config flow for Huawei Solar Power Flow."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_INVERTER_ACTIVE_POWER,
    CONF_INVERTER_INPUT_POWER,
    CONF_POWER_METER_ACTIVE_POWER,
    DEFAULT_BATTERY_POWER,
    DEFAULT_BATTERY_SOC,
    DEFAULT_INVERTER_ACTIVE_POWER,
    DEFAULT_INVERTER_INPUT_POWER,
    DEFAULT_POWER_METER_ACTIVE_POWER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

ENTITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor")
)


def _build_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the config schema with optional defaults."""
    if defaults is None:
        defaults = {}
    return vol.Schema(
        {
            vol.Required(
                CONF_INVERTER_ACTIVE_POWER,
                default=defaults.get(
                    CONF_INVERTER_ACTIVE_POWER, DEFAULT_INVERTER_ACTIVE_POWER
                ),
            ): ENTITY_SELECTOR,
            vol.Required(
                CONF_INVERTER_INPUT_POWER,
                default=defaults.get(
                    CONF_INVERTER_INPUT_POWER, DEFAULT_INVERTER_INPUT_POWER
                ),
            ): ENTITY_SELECTOR,
            vol.Required(
                CONF_POWER_METER_ACTIVE_POWER,
                default=defaults.get(
                    CONF_POWER_METER_ACTIVE_POWER, DEFAULT_POWER_METER_ACTIVE_POWER
                ),
            ): ENTITY_SELECTOR,
            vol.Required(
                CONF_BATTERY_POWER,
                default=defaults.get(CONF_BATTERY_POWER, DEFAULT_BATTERY_POWER),
            ): ENTITY_SELECTOR,
            vol.Optional(
                CONF_BATTERY_SOC,
                default=defaults.get(CONF_BATTERY_SOC, DEFAULT_BATTERY_SOC),
            ): ENTITY_SELECTOR,
        }
    )


class HuaweiSolarPowerFlowConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Huawei Solar Power Flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate that the entities exist
            for key in (
                CONF_INVERTER_ACTIVE_POWER,
                CONF_INVERTER_INPUT_POWER,
                CONF_POWER_METER_ACTIVE_POWER,
                CONF_BATTERY_POWER,
            ):
                entity_id = user_input.get(key, "")
                state = self.hass.states.get(entity_id)
                if state is None:
                    errors[key] = "entity_not_found"

            if not errors:
                # Prevent duplicate entries
                await self.async_set_unique_id("huawei_solar_power_flow")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Huawei Solar Power Flow",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return HuaweiSolarPowerFlowOptionsFlow(config_entry)


class HuaweiSolarPowerFlowOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Huawei Solar Power Flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(dict(self.config_entry.data)),
        )
