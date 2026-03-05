"""Huawei Solar Power Flow integration for Home Assistant.

Creates derived power flow sensors from the Huawei Solar integration,
with correct sign conventions, Modbus glitch filtering, and temporal
coherence checking via a shared coordinator.

Architecture (v1.1.0):
  __init__.py  -> Creates PowerFlowCoordinator, starts it, stores in hass.data
  coordinator.py -> Listens to 4 source sensors, checks coherence, calculates
  sensor.py    -> 12 thin sensor wrappers that read from the coordinator
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BATTERY_POWER,
    CONF_INVERTER_ACTIVE_POWER,
    CONF_INVERTER_INPUT_POWER,
    CONF_POWER_METER_ACTIVE_POWER,
    DOMAIN,
)
from .coordinator import PowerFlowCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Huawei Solar Power Flow from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = entry.data
    source_entities = {
        CONF_INVERTER_ACTIVE_POWER: config[CONF_INVERTER_ACTIVE_POWER],
        CONF_INVERTER_INPUT_POWER: config[CONF_INVERTER_INPUT_POWER],
        CONF_POWER_METER_ACTIVE_POWER: config[CONF_POWER_METER_ACTIVE_POWER],
        CONF_BATTERY_POWER: config[CONF_BATTERY_POWER],
    }

    # Create and start the coordinator
    coordinator = PowerFlowCoordinator(hass, source_entities)
    await coordinator.async_start()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "config": config,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info(
        "Huawei Solar Power Flow integration loaded with coherence-checked "
        "coordinator (sources: %s)",
        source_entities,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Stop the coordinator first
    entry_data = hass.data[DOMAIN].get(entry.entry_id)
    if entry_data and "coordinator" in entry_data:
        await entry_data["coordinator"].async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
