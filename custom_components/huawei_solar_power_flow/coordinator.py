"""Power Flow Coordinator for Huawei Solar Power Flow.

Centralized coordinator that listens to all 4 raw Huawei Solar sensors
and publishes computed power flow values to all 12 derived sensors.

Modbus TCP Glitch Resilience (value-based):
  The Huawei Solar integration polls Modbus registers in batches on a ~30s
  cycle. Source sensors update at different times and idle sensors (e.g.
  battery at 0W) may not fire state_change events at all. Timestamp-based
  coherence doesn't work here.

  Instead, we use value-based sanity checking:
  1. Always recalculate on every source state_change
  2. After calculating, run energy conservation sanity checks
  3. If values are sane: publish them
  4. If impossible (large conservation violations): hold previous values
  5. Zero-rejection filter catches sudden drops to zero
  6. Unavailable/unknown source states -> mark all unavailable
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BATTERY_POWER,
    CONF_INVERTER_ACTIVE_POWER,
    CONF_INVERTER_INPUT_POWER,
    CONF_POWER_METER_ACTIVE_POWER,
    EXCLUSIVE_PAIRS,
    SANITY_TOLERANCE_WATTS,
    ZERO_REJECT_MAX_HOLDS,
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


class PowerFlowCoordinator:
    """Coordinate power flow calculations with sanity checking.

    Instead of each sensor independently listening and recalculating,
    this coordinator:
    1. Listens to all 4 source sensors (once)
    2. On any change, recalculates all 12 values
    3. Runs energy conservation sanity checks on the results
    4. If sane: publishes new values to all 12 sensors
    5. If impossible: holds previous valid values (glitch protection)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source_entities: dict[str, str],
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self._source_entities = source_entities
        self._listeners: list[callback] = []
        self._unsub: CALLBACK_TYPE | None = None

        # Current computed values for all 12 sensors
        self._values: dict[str, float | None] = {}
        # Previous valid values for zero-rejection and hold-on-glitch
        self._previous_values: dict[str, float] = {}
        # Zero-rejection hold counters: how many consecutive calculations
        # each sensor has been held at its previous value instead of zero.
        # Resets to 0 when a non-zero value is accepted.
        self._zero_hold_counts: dict[str, int] = {}
        # Whether the system is available
        self._available: bool = False
        # Whether we're currently holding stale values due to a glitch
        self._holding: bool = False

    @property
    def available(self) -> bool:
        """Return whether computed values are available."""
        return self._available

    @property
    def holding(self) -> bool:
        """Return whether we're holding previous values due to a glitch."""
        return self._holding

    def get_value(self, sensor_key: str) -> float | None:
        """Get the current computed value for a sensor key."""
        return self._values.get(sensor_key)

    def register_sensor_callback(self, update_callback: callback) -> None:
        """Register a sensor callback to be notified on value changes."""
        self._listeners.append(update_callback)

    def unregister_sensor_callback(self, update_callback: callback) -> None:
        """Unregister a sensor callback."""
        if update_callback in self._listeners:
            self._listeners.remove(update_callback)

    def _notify_sensors(self) -> None:
        """Notify all registered sensors that values have changed."""
        for listener in self._listeners:
            listener()

    async def async_start(self) -> None:
        """Start listening to source sensor state changes."""
        tracked_entities = list(self._source_entities.values())

        @callback
        def _async_source_state_listener(event: Event) -> None:
            """Handle source sensor state changes."""
            entity_id = event.data.get("entity_id", "")
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")

            if new_state is not None:
                _LOGGER.debug(
                    "Source sensor changed: %s = %s (was %s)",
                    entity_id,
                    new_state.state,
                    old_state.state if old_state else "None",
                )

            self._process_update()

        self._unsub = async_track_state_change_event(
            self.hass, tracked_entities, _async_source_state_listener
        )

        # Initial computation
        self._process_update()

    async def async_stop(self) -> None:
        """Stop listening to source sensor state changes."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _process_update(self) -> None:
        """Process a source sensor update.

        Reads all 4 source values, recalculates, and runs sanity checks.
        If any source is unavailable/unknown, marks all derived sensors
        unavailable. If values fail sanity checks, holds previous values.
        """
        from .sensor import PowerFlowCalculator

        # Step 1: Read all source values
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

        # Step 2: If any source is unavailable, mark everything unavailable
        if (
            inverter_active is None
            or inverter_input is None
            or meter is None
            or battery is None
        ):
            unavailable = [
                k for k, v in {
                    CONF_INVERTER_ACTIVE_POWER: inverter_active,
                    CONF_INVERTER_INPUT_POWER: inverter_input,
                    CONF_POWER_METER_ACTIVE_POWER: meter,
                    CONF_BATTERY_POWER: battery,
                }.items() if v is None
            ]
            _LOGGER.debug(
                "Source sensors unavailable: %s — marking derived "
                "sensors unavailable",
                unavailable,
            )
            self._available = False
            self._holding = False
            self._values = {}
            self._notify_sensors()
            return

        # Step 3: Calculate all 12 power flow values
        calc = PowerFlowCalculator(
            inverter_active=inverter_active,
            inverter_input=inverter_input,
            meter=meter,
            battery=battery,
        )

        new_values: dict[str, float] = {}
        for sensor_key in (
            "grid_consumption",
            "grid_feed_in",
            "solar_production",
            "home_consumption",
            "solar_consumption",
            "battery_charge_power",
            "battery_discharge_power",
            "generation_to_grid",
            "generation_to_battery",
            "grid_to_battery",
            "battery_to_house",
            "grid_to_house",
        ):
            new_values[sensor_key] = round(calc.get_value(sensor_key), 1)

        # Step 4: Sanity check — energy conservation
        # These must hold (within tolerance) if source sensors are coherent:
        #   home ≈ solar_consumption + grid_to_house + battery_to_house
        #   solar ≈ gen_to_grid + gen_to_bat + solar_consumption
        #   grid_import ≈ grid_to_house + grid_to_battery
        #   bat_charge ≈ gen_to_bat + grid_to_bat
        #
        # If sources are mismatched (glitch), the raw values won't balance
        # and these checks will catch large violations.
        sane = True
        violations: list[str] = []

        home = new_values["home_consumption"]
        home_sum = (
            new_values["solar_consumption"]
            + new_values["grid_to_house"]
            + new_values["battery_to_house"]
        )
        home_err = abs(home - home_sum)
        if home_err > SANITY_TOLERANCE_WATTS:
            violations.append(
                f"home={home:.0f} vs parts={home_sum:.0f} "
                f"(err={home_err:.0f}W)"
            )
            sane = False

        solar = new_values["solar_production"]
        solar_sum = (
            new_values["generation_to_grid"]
            + new_values["generation_to_battery"]
            + new_values["solar_consumption"]
        )
        solar_err = abs(solar - solar_sum)
        if solar_err > SANITY_TOLERANCE_WATTS:
            violations.append(
                f"solar={solar:.0f} vs parts={solar_sum:.0f} "
                f"(err={solar_err:.0f}W)"
            )
            sane = False

        grid_in = new_values["grid_consumption"]
        grid_in_sum = (
            new_values["grid_to_house"]
            + new_values["grid_to_battery"]
        )
        grid_err = abs(grid_in - grid_in_sum)
        if grid_err > SANITY_TOLERANCE_WATTS:
            violations.append(
                f"grid_import={grid_in:.0f} vs parts={grid_in_sum:.0f} "
                f"(err={grid_err:.0f}W)"
            )
            sane = False

        bat_charge = new_values["battery_charge_power"]
        bat_charge_sum = (
            new_values["generation_to_battery"]
            + new_values["grid_to_battery"]
        )
        bat_err = abs(bat_charge - bat_charge_sum)
        if bat_err > SANITY_TOLERANCE_WATTS:
            violations.append(
                f"bat_charge={bat_charge:.0f} vs parts={bat_charge_sum:.0f} "
                f"(err={bat_err:.0f}W)"
            )
            sane = False

        # Step 5: Handle sanity result
        if not sane and self._previous_values:
            # Values are impossible and we have previous good values — hold
            if not self._holding:
                _LOGGER.warning(
                    "Modbus glitch detected: energy conservation violated. "
                    "Holding previous values. Violations: %s. "
                    "Raw: inv_act=%.0f inv_inp=%.0f meter=%.0f bat=%.0f",
                    violations,
                    inverter_active,
                    inverter_input,
                    meter,
                    battery,
                )
                self._holding = True
            self._available = True
            # Don't update values, don't notify — keep showing previous
            return

        if self._holding and sane:
            _LOGGER.info(
                "Modbus glitch resolved: energy conservation restored. "
                "Resuming normal calculation."
            )

        self._holding = False

        # Step 6: Apply zero-rejection filter with TTL and exclusive pairs
        #
        # Zero-rejection catches brief Modbus zero-spikes: if a sensor drops
        # to exactly 0 but was previously above threshold, hold the previous
        # value for up to ZERO_REJECT_MAX_HOLDS consecutive calculations.
        #
        # Exclusive pairs: when the calculator produces a non-zero value for
        # one side of a mutually exclusive pair (e.g. battery_charge_power),
        # the opposite side (battery_discharge_power) must accept zero
        # immediately — the transition is real, not a glitch.

        # Build set of sensors whose opposite in an exclusive pair is non-zero
        # in this calculation — these must NOT be zero-rejected.
        force_accept_zero: set[str] = set()
        for sensor_a, sensor_b in EXCLUSIVE_PAIRS:
            if new_values.get(sensor_a, 0.0) > 0.0:
                force_accept_zero.add(sensor_b)
            if new_values.get(sensor_b, 0.0) > 0.0:
                force_accept_zero.add(sensor_a)

        final_values: dict[str, float] = {}
        for sensor_key, raw_value in new_values.items():
            threshold = (
                ZERO_REJECT_THRESHOLD_SOLAR
                if sensor_key == "solar_production"
                else ZERO_REJECT_THRESHOLD_DEFAULT
            )
            prev = self._previous_values.get(sensor_key)
            hold_count = self._zero_hold_counts.get(sensor_key, 0)

            if (
                raw_value == 0.0
                and prev is not None
                and prev > threshold
                and sensor_key not in force_accept_zero
                and hold_count < ZERO_REJECT_MAX_HOLDS
            ):
                # Hold previous value — likely a brief Modbus zero-spike
                self._zero_hold_counts[sensor_key] = hold_count + 1
                _LOGGER.debug(
                    "Zero-rejection on %s: holding previous value %.1f "
                    "(hold %d/%d, threshold: %.1f)",
                    sensor_key,
                    prev,
                    hold_count + 1,
                    ZERO_REJECT_MAX_HOLDS,
                    threshold,
                )
                final_values[sensor_key] = prev
            else:
                # Accept the new value (zero or non-zero)
                if (
                    raw_value == 0.0
                    and hold_count >= ZERO_REJECT_MAX_HOLDS
                    and prev is not None
                    and prev > threshold
                ):
                    _LOGGER.debug(
                        "Zero-rejection expired on %s: accepting zero "
                        "after %d holds (was %.1f)",
                        sensor_key,
                        hold_count,
                        prev,
                    )
                elif (
                    raw_value == 0.0
                    and sensor_key in force_accept_zero
                    and prev is not None
                    and prev > threshold
                ):
                    _LOGGER.debug(
                        "Zero-rejection overridden on %s: exclusive pair "
                        "active, accepting zero (was %.1f)",
                        sensor_key,
                        prev,
                    )
                self._zero_hold_counts[sensor_key] = 0
                final_values[sensor_key] = raw_value

        # Step 7: Publish
        self._values: dict[str, float | None] = dict(final_values)
        self._previous_values = dict(final_values)
        self._available = True

        _LOGGER.debug(
            "Calculation complete: solar=%.0f home=%.0f "
            "grid_in=%.0f grid_out=%.0f bat_chg=%.0f bat_dis=%.0f",
            final_values.get("solar_production", 0),
            final_values.get("home_consumption", 0),
            final_values.get("grid_consumption", 0),
            final_values.get("grid_feed_in", 0),
            final_values.get("battery_charge_power", 0),
            final_values.get("battery_discharge_power", 0),
        )

        self._notify_sensors()
