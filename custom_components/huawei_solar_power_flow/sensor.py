"""Sensor platform for Huawei Solar Power Flow.

Creates 12 derived power flow sensors from Huawei Solar integration entities,
with correct sign conventions and Modbus glitch filtering (zero-rejection).

Huawei SUN2000 Sign Conventions (verified with FusionSolar):
  inverter_active_power: positive = producing, negative = consuming
    NOTE: total AC bus power = solar + battery_discharge - battery_charge
  inverter_input_power: always >= 0, pure DC solar panel input
  power_meter_active_power: positive = EXPORTING, negative = IMPORTING
  batteries_charge_discharge_power: positive = charging, negative = discharging
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_INVERTER_ACTIVE_POWER,
    CONF_INVERTER_INPUT_POWER,
    CONF_POWER_METER_ACTIVE_POWER,
    DOMAIN,
    SENSOR_TYPES,
    ZERO_REJECT_THRESHOLD_DEFAULT,
    ZERO_REJECT_THRESHOLD_SOLAR,
)

_LOGGER = logging.getLogger(__name__)


def _float_or_none(hass: HomeAssistant, entity_id: str) -> float | None:
    """Get float value from entity state, or None if unavailable."""
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unavailable", "unknown", ""):
        return None
    try:
        return float(state.state)
    except (ValueError, TypeError):
        return None


class PowerFlowCalculator:
    """Calculate all 12 power flow values from raw Huawei sensors.

    All outputs are in Watts, always >= 0.
    """

    def __init__(
        self,
        inverter_active: float,
        inverter_input: float,
        meter: float,
        battery: float,
    ) -> None:
        """Initialize with raw sensor values."""
        self._inverter_active = inverter_active
        self._inverter_input = inverter_input
        self._meter = meter
        self._battery = battery

        # Pre-compute derived values
        self._grid_import = max(-self._meter, 0.0)
        self._grid_export = max(self._meter, 0.0)
        self._solar = max(self._inverter_input, 0.0)
        self._bat_charge = max(self._battery, 0.0)
        self._bat_discharge = max(-self._battery, 0.0)
        self._home = max(self._inverter_active - self._meter, 0.0)
        self._gen_to_bat = min(self._solar, self._bat_charge)
        self._grid_to_bat = max(self._bat_charge - self._gen_to_bat, 0.0)

    @property
    def grid_consumption(self) -> float:
        """Power drawn FROM the grid (W, >= 0)."""
        return self._grid_import

    @property
    def grid_feed_in(self) -> float:
        """Power exported TO the grid (W, >= 0)."""
        return self._grid_export

    @property
    def solar_production(self) -> float:
        """Pure DC solar panel power (W, >= 0)."""
        return self._solar

    @property
    def home_consumption(self) -> float:
        """Total house power draw (W, >= 0)."""
        return self._home

    @property
    def solar_consumption(self) -> float:
        """Solar power consumed by the house (W, >= 0)."""
        return min(self._solar, self._home)

    @property
    def battery_charge_power(self) -> float:
        """Battery charging power (W, >= 0)."""
        return self._bat_charge

    @property
    def battery_discharge_power(self) -> float:
        """Battery discharging power (W, >= 0)."""
        return self._bat_discharge

    @property
    def generation_to_grid(self) -> float:
        """Solar power exported to grid (W, >= 0)."""
        return min(self._solar, self._grid_export)

    @property
    def generation_to_battery(self) -> float:
        """Solar power charging battery (W, >= 0)."""
        return self._gen_to_bat

    @property
    def grid_to_battery(self) -> float:
        """Grid power charging battery (W, >= 0)."""
        return self._grid_to_bat

    @property
    def battery_to_house(self) -> float:
        """Battery discharge going to house (W, >= 0)."""
        return self._bat_discharge

    @property
    def grid_to_house(self) -> float:
        """Grid power consumed by house (W, >= 0)."""
        return max(self._grid_import - self._grid_to_bat, 0.0)

    def get_value(self, sensor_key: str) -> float:
        """Get computed value by sensor key."""
        return getattr(self, sensor_key)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Huawei Solar Power Flow sensors from config entry."""
    config = entry.data

    source_entities = {
        CONF_INVERTER_ACTIVE_POWER: config[CONF_INVERTER_ACTIVE_POWER],
        CONF_INVERTER_INPUT_POWER: config[CONF_INVERTER_INPUT_POWER],
        CONF_POWER_METER_ACTIVE_POWER: config[CONF_POWER_METER_ACTIVE_POWER],
        CONF_BATTERY_POWER: config[CONF_BATTERY_POWER],
    }

    battery_soc_entity = config.get(CONF_BATTERY_SOC)

    sensors: list[HuaweiSolarPowerFlowSensor] = []
    for sensor_key, sensor_info in SENSOR_TYPES.items():
        threshold = (
            ZERO_REJECT_THRESHOLD_SOLAR
            if sensor_key == "solar_production"
            else ZERO_REJECT_THRESHOLD_DEFAULT
        )
        sensors.append(
            HuaweiSolarPowerFlowSensor(
                entry=entry,
                sensor_key=sensor_key,
                name=sensor_info["name"],
                description=sensor_info["description"],
                source_entities=source_entities,
                zero_reject_threshold=threshold,
            )
        )

    async_add_entities(sensors)


class HuaweiSolarPowerFlowSensor(SensorEntity):
    """A derived power flow sensor for Huawei Solar."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        sensor_key: str,
        name: str,
        description: str,
        source_entities: dict[str, str],
        zero_reject_threshold: float,
    ) -> None:
        """Initialize the sensor."""
        self._sensor_key = sensor_key
        self._source_entities = source_entities
        self._zero_reject_threshold = zero_reject_threshold
        self._previous_value: float | None = None

        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{sensor_key}"
        self._attr_extra_state_attributes = {
            "description": description,
            "source_entities": source_entities,
        }

    async def async_added_to_hass(self) -> None:
        """Register state listeners when added to hass."""
        tracked_entities = list(self._source_entities.values())

        @callback
        def _async_sensor_state_listener(
            event: Event,
        ) -> None:
            """Handle source sensor state changes."""
            self._update_state()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, tracked_entities, _async_sensor_state_listener
            )
        )

        # Initial state computation
        self._update_state()

    @callback
    def _update_state(self) -> None:
        """Recalculate sensor value from source entities."""
        inverter_active = _float_or_none(
            self.hass, self._source_entities[CONF_INVERTER_ACTIVE_POWER]
        )
        inverter_input = _float_or_none(
            self.hass, self._source_entities[CONF_INVERTER_INPUT_POWER]
        )
        meter = _float_or_none(
            self.hass, self._source_entities[CONF_POWER_METER_ACTIVE_POWER]
        )
        battery = _float_or_none(
            self.hass, self._source_entities[CONF_BATTERY_POWER]
        )

        # Check availability: all required sources must have valid values
        if (
            inverter_active is None
            or inverter_input is None
            or meter is None
            or battery is None
        ):
            self._attr_available = False
            return

        self._attr_available = True

        calc = PowerFlowCalculator(
            inverter_active=inverter_active,
            inverter_input=inverter_input,
            meter=meter,
            battery=battery,
        )

        new_value = round(calc.get_value(self._sensor_key), 1)

        # Zero-rejection filter: if new value is 0 but previous was above
        # threshold, hold previous value (Modbus glitch protection)
        if (
            new_value == 0.0
            and self._previous_value is not None
            and self._previous_value > self._zero_reject_threshold
        ):
            _LOGGER.debug(
                "Zero-rejection on %s: holding previous value %.1f "
                "(threshold: %.1f)",
                self._sensor_key,
                self._previous_value,
                self._zero_reject_threshold,
            )
            self._attr_native_value = self._previous_value
            return

        self._previous_value = new_value
        self._attr_native_value = new_value
