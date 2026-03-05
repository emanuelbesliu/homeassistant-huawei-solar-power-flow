"""Sensor platform for Huawei Solar Power Flow.

Creates 12 derived power flow sensors from Huawei Solar integration entities,
with correct sign conventions, Modbus glitch filtering (zero-rejection),
and temporal coherence checking (coordinator pattern).

Huawei SUN2000 Sign Conventions (verified with FusionSolar):
  inverter_active_power: positive = producing, negative = consuming
    NOTE: total AC bus power = solar + battery_discharge - battery_charge
  inverter_input_power: always >= 0, pure DC solar panel input
  power_meter_active_power: positive = EXPORTING, negative = IMPORTING
  batteries_charge_discharge_power: positive = charging, negative = discharging

Architecture (v1.1.0):
  PowerFlowCoordinator (coordinator.py):
    - Single listener for all 4 source sensors
    - Checks temporal coherence before recalculating
    - Holds previous values during Modbus glitches
    - Notifies all 12 sensors when values change

  HuaweiSolarPowerFlowSensor (this file):
    - Thin wrapper that reads computed value from coordinator
    - No direct source sensor listening or calculation
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SENSOR_TYPES
from .coordinator import PowerFlowCoordinator

_LOGGER = logging.getLogger(__name__)


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
        """Initialize with raw sensor values.

        Energy conservation rules enforced:
          solar = generation_to_grid + generation_to_battery + solar_consumption
          grid_import = grid_to_house + grid_to_battery
          bat_charge = generation_to_battery + grid_to_battery
          bat_discharge = battery_to_house  (+ battery_to_grid if applicable)
          home = solar_consumption + grid_to_house + battery_to_house
        """
        self._inverter_active = inverter_active
        self._inverter_input = inverter_input
        self._meter = meter
        self._battery = battery

        # --- Absolute values from signed raw sensors ---
        self._grid_import = max(-self._meter, 0.0)
        self._grid_export = max(self._meter, 0.0)
        self._solar = max(self._inverter_input, 0.0)
        self._bat_charge = max(self._battery, 0.0)
        self._bat_discharge = max(-self._battery, 0.0)
        self._home = max(self._inverter_active - self._meter, 0.0)

        # --- Allocate solar to destinations from a shared budget ---
        # Priority: battery first (physical: MPPT charges battery directly),
        # then grid export, then house gets the remainder.
        solar_budget = self._solar

        # 1) Solar -> Battery: limited by both solar available and charge demand
        self._gen_to_bat = min(solar_budget, self._bat_charge)
        solar_budget -= self._gen_to_bat

        # 2) Solar -> Grid: limited by remaining solar and grid export
        self._gen_to_grid = min(solar_budget, self._grid_export)
        solar_budget -= self._gen_to_grid

        # 3) Solar -> House: whatever solar remains
        self._solar_consumption = solar_budget

        # --- Non-solar flows ---
        # Grid -> Battery: any battery charge not covered by solar
        self._grid_to_bat = max(self._bat_charge - self._gen_to_bat, 0.0)

        # Grid -> House: grid import minus what goes to battery
        self._grid_to_house = max(self._grid_import - self._grid_to_bat, 0.0)

        # Battery -> House: all battery discharge goes to house
        # (Huawei systems don't do battery-to-grid feed-in)
        self._bat_to_house = self._bat_discharge

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
        return self._solar_consumption

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
        return self._gen_to_grid

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
        return self._bat_to_house

    @property
    def grid_to_house(self) -> float:
        """Grid power consumed by house (W, >= 0)."""
        return self._grid_to_house

    def get_value(self, sensor_key: str) -> float:
        """Get computed value by sensor key."""
        return getattr(self, sensor_key)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Huawei Solar Power Flow sensors from config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    sensors: list[HuaweiSolarPowerFlowSensor] = []
    for sensor_key, sensor_info in SENSOR_TYPES.items():
        sensors.append(
            HuaweiSolarPowerFlowSensor(
                entry=entry,
                sensor_key=sensor_key,
                name=sensor_info["name"],
                description=sensor_info["description"],
                coordinator=coordinator,
            )
        )

    async_add_entities(sensors)


class HuaweiSolarPowerFlowSensor(SensorEntity):
    """A derived power flow sensor for Huawei Solar.

    Thin wrapper that reads its value from the shared PowerFlowCoordinator.
    The coordinator handles all source sensor listening, coherence checking,
    and calculation. This sensor just renders the coordinator's output.
    """

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
        coordinator: PowerFlowCoordinator,
    ) -> None:
        """Initialize the sensor."""
        self._sensor_key = sensor_key
        self._coordinator = coordinator

        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{sensor_key}"
        self._attr_extra_state_attributes = {
            "description": description,
        }

    async def async_added_to_hass(self) -> None:
        """Register with coordinator when added to hass."""

        @callback
        def _async_coordinator_updated() -> None:
            """Handle coordinator value updates."""
            self._update_from_coordinator()
            self.async_write_ha_state()

        self._coordinator.register_sensor_callback(_async_coordinator_updated)

        # Store callback ref for cleanup
        self._update_callback = _async_coordinator_updated

        # Initial state from coordinator
        self._update_from_coordinator()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister from coordinator when removed."""
        if hasattr(self, "_update_callback"):
            self._coordinator.unregister_sensor_callback(self._update_callback)

    @callback
    def _update_from_coordinator(self) -> None:
        """Read current value from coordinator."""
        self._attr_available = self._coordinator.available
        value = self._coordinator.get_value(self._sensor_key)
        self._attr_native_value = value

        # Expose coherence status in attributes for debugging
        self._attr_extra_state_attributes = {
            **self._attr_extra_state_attributes,
            "holding_previous": self._coordinator.holding,
        }
