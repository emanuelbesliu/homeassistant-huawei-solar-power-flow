"""Constants for Huawei Solar Power Flow."""

DOMAIN = "huawei_solar_power_flow"
VERSION = "1.1.1"

# Configuration keys
CONF_INVERTER_ACTIVE_POWER = "inverter_active_power"
CONF_INVERTER_INPUT_POWER = "inverter_input_power"
CONF_POWER_METER_ACTIVE_POWER = "power_meter_active_power"
CONF_BATTERY_POWER = "battery_power"
CONF_BATTERY_SOC = "battery_soc"

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

# Zero-rejection thresholds (W) for Modbus glitch filtering.
# If a sensor's calculated value drops to exactly 0 but was previously above
# the threshold, hold the previous value for up to ZERO_REJECT_MAX_HOLDS
# consecutive calculations. This catches brief Modbus zero-spikes without
# permanently holding stale values.
ZERO_REJECT_THRESHOLD_SOLAR = 100.0
ZERO_REJECT_THRESHOLD_DEFAULT = 50.0

# Maximum number of consecutive calculations a zero-rejected value is held.
# At ~30s poll interval this is ~90s. After this, the zero is accepted as
# real (the source genuinely stopped producing/consuming).
ZERO_REJECT_MAX_HOLDS = 3

# Mutually exclusive sensor pairs. By physics, only one side of each pair
# can be non-zero at a time. When the calculator produces a non-zero value
# for one side, the opposite side's zero-rejection hold must be cleared
# immediately — the transition is real, not a glitch.
EXCLUSIVE_PAIRS: list[tuple[str, str]] = [
    ("battery_charge_power", "battery_discharge_power"),
    ("grid_consumption", "grid_feed_in"),
    ("generation_to_battery", "grid_to_battery"),
]

# Energy conservation sanity tolerance (W). After calculating all 12 derived
# flows, the coordinator checks that energy balances hold (e.g. home power
# equals sum of solar_consumption + grid_to_house + battery_to_house). If
# any balance is violated by more than this tolerance, the values are likely
# from mismatched source sensors (Modbus glitch) and previous values are held.
# Set generously to avoid false positives from rounding and inverter losses.
SANITY_TOLERANCE_WATTS = 500.0

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
