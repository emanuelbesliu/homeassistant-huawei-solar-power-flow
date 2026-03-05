"""Constants for Huawei Solar Power Flow."""

DOMAIN = "huawei_solar_power_flow"
VERSION = "1.1.0"

# Configuration keys
CONF_INVERTER_ACTIVE_POWER = "inverter_active_power"
CONF_INVERTER_INPUT_POWER = "inverter_input_power"
CONF_POWER_METER_ACTIVE_POWER = "power_meter_active_power"
CONF_BATTERY_POWER = "battery_power"
CONF_BATTERY_SOC = "battery_soc"

# Ordered list of the 4 required source sensor config keys
SOURCE_KEYS: list[str] = [
    CONF_INVERTER_ACTIVE_POWER,
    CONF_INVERTER_INPUT_POWER,
    CONF_POWER_METER_ACTIVE_POWER,
    CONF_BATTERY_POWER,
]

# Default Huawei Solar entity IDs
DEFAULT_INVERTER_ACTIVE_POWER = "sensor.inverter_active_power"
DEFAULT_INVERTER_INPUT_POWER = "sensor.inverter_input_power"
DEFAULT_POWER_METER_ACTIVE_POWER = "sensor.power_meter_active_power"
DEFAULT_BATTERY_POWER = "sensor.batteries_charge_discharge_power"
DEFAULT_BATTERY_SOC = "sensor.batteries_state_of_capacity"

# Huawei SUN2000 Sign Conventions (verified with FusionSolar):
#   inverter_active_power: positive = producing (AC output),
#                          negative = consuming (AC battery charging)
#     NOTE: This is total AC bus power = solar + battery_discharge - battery_charge
#   inverter_input_power:  always >= 0, pure DC solar panel input
#   power_meter_active_power: positive = EXPORTING to grid,
#                             negative = IMPORTING from grid
#   batteries_charge_discharge_power: positive = charging,
#                                     negative = discharging

# Zero-rejection thresholds (W) for Modbus glitch filtering
ZERO_REJECT_THRESHOLD_SOLAR = 100.0
ZERO_REJECT_THRESHOLD_DEFAULT = 50.0

# Coherence window: max allowed spread (seconds) between source sensor
# last_updated timestamps. If spread exceeds this, sensors are considered
# temporally mismatched (Modbus glitch) and previous values are held.
# Huawei Solar polls all registers in one batch (~30s default interval),
# so on a healthy connection all 4 sensors update within milliseconds.
# 15s allows for minor jitter without false-triggering.
COHERENCE_WINDOW_SECONDS = 15.0

# Staleness timeout: if the newest source sensor hasn't updated in this many
# seconds, all derived sensors are marked unavailable. This catches the case
# where the entire Modbus connection is down (not just partial glitches).
# Set to 3x the default poll interval (30s * 3 = 90s).
STALENESS_TIMEOUT_SECONDS = 90.0

# Sensor definitions: (key, name, description)
SENSOR_TYPES = {
    "grid_consumption": {
        "name": "Grid Consumption",
        "description": "Power drawn from the grid",
    },
    "grid_feed_in": {
        "name": "Grid Feed In",
        "description": "Power exported to the grid",
    },
    "solar_production": {
        "name": "Solar Production",
        "description": "Pure DC solar panel power",
    },
    "home_consumption": {
        "name": "Home Consumption",
        "description": "Total house power draw",
    },
    "solar_consumption": {
        "name": "Solar Consumption",
        "description": "Solar power consumed by the house",
    },
    "battery_charge_power": {
        "name": "Battery Charge Power",
        "description": "Battery charging power",
    },
    "battery_discharge_power": {
        "name": "Battery Discharge Power",
        "description": "Battery discharging power",
    },
    "generation_to_grid": {
        "name": "Generation To Grid",
        "description": "Solar power exported to grid",
    },
    "generation_to_battery": {
        "name": "Generation To Battery",
        "description": "Solar power charging battery",
    },
    "grid_to_battery": {
        "name": "Grid To Battery",
        "description": "Grid power charging battery",
    },
    "battery_to_house": {
        "name": "Battery To House",
        "description": "Battery discharge going to house",
    },
    "grid_to_house": {
        "name": "Grid To House",
        "description": "Grid power consumed by house",
    },
}
