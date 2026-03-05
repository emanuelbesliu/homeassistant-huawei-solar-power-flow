"""Power Flow Coordinator for Huawei Solar Power Flow.

Centralized coordinator that listens to all 4 raw Huawei Solar sensors,
enforces temporal coherence (all sources must update within a tight window),
and publishes computed power flow values to all 12 derived sensors.

Modbus TCP Glitch Resilience:
  - Normal: all 4 sources update within ~15s of each other -> recalculate
  - Glitch: some sensors stale while others update -> hold previous values
  - Offline: all sensors stale > 90s -> mark unavailable
  - Recovery: coherence restored -> immediately recalculate
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    COHERENCE_WINDOW_SECONDS,
    CONF_BATTERY_POWER,
    CONF_INVERTER_ACTIVE_POWER,
    CONF_INVERTER_INPUT_POWER,
    CONF_POWER_METER_ACTIVE_POWER,
    SOURCE_KEYS,
    STALENESS_TIMEOUT_SECONDS,
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


def _get_last_updated(hass: HomeAssistant, entity_id: str) -> datetime | None:
    """Get last_updated timestamp from entity state."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return state.last_updated


class PowerFlowCoordinator:
    """Coordinate power flow calculations with temporal coherence checks.

    Instead of each sensor independently listening and recalculating,
    this coordinator:
    1. Listens to all 4 source sensors (once)
    2. On any change, checks if all sources are temporally coherent
    3. If coherent: recalculates all 12 values and notifies sensors
    4. If not coherent: holds previous values (glitch protection)
    5. If all stale: marks everything unavailable
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
        # Whether the system is available (coherent or held)
        self._available: bool = False
        # Whether we're currently holding stale values due to a glitch
        self._holding: bool = False
        # Track last coherent calculation time
        self._last_coherent_calc: datetime | None = None

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
        """Process a source sensor update with coherence checking."""
        now = datetime.now(timezone.utc)

        # Step 1: Get last_updated timestamps for all sources
        timestamps: dict[str, datetime | None] = {}
        for key in SOURCE_KEYS:
            entity_id = self._source_entities[key]
            timestamps[key] = _get_last_updated(self.hass, entity_id)

        # Step 2: Check if any source is completely missing
        valid_timestamps = {
            k: v for k, v in timestamps.items() if v is not None
        }

        if len(valid_timestamps) < len(SOURCE_KEYS):
            missing = [
                k for k in SOURCE_KEYS if timestamps[k] is None
            ]
            _LOGGER.debug(
                "Source sensors missing state: %s — marking unavailable",
                missing,
            )
            self._available = False
            self._holding = False
            self._values = {}
            self._notify_sensors()
            return

        # Step 3: Check temporal coherence
        ts_values = list(valid_timestamps.values())
        newest = max(ts_values)
        oldest = min(ts_values)
        spread_seconds = (newest - oldest).total_seconds()

        # Step 4: Check for total staleness (all sensors too old)
        age_of_newest = (now - newest).total_seconds()
        if age_of_newest > STALENESS_TIMEOUT_SECONDS:
            if self._available:
                _LOGGER.warning(
                    "All source sensors stale (newest: %.0fs ago, "
                    "timeout: %ds) — marking unavailable",
                    age_of_newest,
                    STALENESS_TIMEOUT_SECONDS,
                )
            self._available = False
            self._holding = False
            self._values = {}
            self._notify_sensors()
            return

        # Step 5: Check coherence window
        if spread_seconds > COHERENCE_WINDOW_SECONDS:
            # Temporal mismatch detected — some sensors updated, others stale
            if not self._holding:
                stale_sources = {
                    k: (newest - v).total_seconds()
                    for k, v in valid_timestamps.items()
                    if (newest - v).total_seconds() > COHERENCE_WINDOW_SECONDS
                }
                _LOGGER.warning(
                    "Modbus glitch detected: sensor timestamp spread %.1fs "
                    "(threshold: %ds). Stale sources: %s — holding "
                    "previous values",
                    spread_seconds,
                    COHERENCE_WINDOW_SECONDS,
                    {k: f"{v:.0f}s behind" for k, v in stale_sources.items()},
                )
                self._holding = True

            # Keep previous values, stay available if we had values before
            if self._previous_values:
                self._available = True
            else:
                # No previous values to hold — can't display anything
                self._available = False

            # Don't recalculate, don't notify (values unchanged)
            return

        # Step 6: Sources are coherent — recalculate
        if self._holding:
            _LOGGER.info(
                "Modbus coherence restored (spread: %.1fs) — resuming "
                "normal calculation",
                spread_seconds,
            )
            self._holding = False

        self._recalculate(now)

    @callback
    def _recalculate(self, now: datetime) -> None:
        """Recalculate all 12 power flow values from coherent sources."""
        # Import here to avoid circular dependency
        from .sensor import PowerFlowCalculator

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

        # All sources must have valid numeric values
        if (
            inverter_active is None
            or inverter_input is None
            or meter is None
            or battery is None
        ):
            _LOGGER.debug("One or more source values are non-numeric — skipping")
            self._available = False
            self._values = {}
            self._notify_sensors()
            return

        calc = PowerFlowCalculator(
            inverter_active=inverter_active,
            inverter_input=inverter_input,
            meter=meter,
            battery=battery,
        )

        # Compute all 12 values with zero-rejection filtering
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
            raw_value = round(calc.get_value(sensor_key), 1)

            # Zero-rejection filter
            threshold = (
                ZERO_REJECT_THRESHOLD_SOLAR
                if sensor_key == "solar_production"
                else ZERO_REJECT_THRESHOLD_DEFAULT
            )
            prev = self._previous_values.get(sensor_key)

            if raw_value == 0.0 and prev is not None and prev > threshold:
                _LOGGER.debug(
                    "Zero-rejection on %s: holding previous value %.1f "
                    "(threshold: %.1f)",
                    sensor_key,
                    prev,
                    threshold,
                )
                new_values[sensor_key] = prev
            else:
                new_values[sensor_key] = raw_value

        self._values: dict[str, float | None] = dict(new_values)
        self._previous_values = dict(new_values)
        self._available = True
        self._last_coherent_calc = now

        _LOGGER.debug(
            "Coherent recalculation complete: solar=%.0f home=%.0f "
            "grid_in=%.0f grid_out=%.0f bat_chg=%.0f bat_dis=%.0f",
            new_values.get("solar_production", 0),
            new_values.get("home_consumption", 0),
            new_values.get("grid_consumption", 0),
            new_values.get("grid_feed_in", 0),
            new_values.get("battery_charge_power", 0),
            new_values.get("battery_discharge_power", 0),
        )

        self._notify_sensors()
