# Huawei Solar Power Flow

[![HACS][hacs-badge]][hacs-url]
[![GitHub Release][release-badge]][release-url]
[![License][license-badge]][license-url]

A Home Assistant custom integration that creates **12 derived power flow sensors** from the [Huawei Solar](https://github.com/wlcrs/huawei_solar) integration. Designed for **Huawei SUN2000 inverters** with battery (LUNA2000), but works with any Huawei Solar setup.

Includes **Modbus glitch filtering** (zero-rejection) to prevent spurious readings from corrupting your energy dashboard.

## Features

- **12 power flow sensors** with correct Huawei sign conventions
- **Zero-rejection filter** prevents Modbus TCP connection drops from producing false 0W readings
- **Config flow UI** -- set up entirely from the Home Assistant UI, no YAML needed
- **Auto-updates** via state change listeners (no polling delay)
- **Ready for Tesla-style solar power card** -- sensors map directly to the card's entity slots
- **Ready for Energy Dashboard** -- all sensors have proper `device_class`, `state_class`, and `unit_of_measurement`

## Sensors Created

| Sensor | Description |
|---|---|
| `sensor.grid_consumption` | Power drawn from the grid (W) |
| `sensor.grid_feed_in` | Power exported to the grid (W) |
| `sensor.solar_production` | Pure DC solar panel power (W) |
| `sensor.home_consumption` | Total house power draw (W) |
| `sensor.solar_consumption` | Solar power consumed by house (W) |
| `sensor.battery_charge_power` | Battery charging power (W) |
| `sensor.battery_discharge_power` | Battery discharging power (W) |
| `sensor.generation_to_grid` | Solar power exported to grid (W) |
| `sensor.generation_to_battery` | Solar power charging battery (W) |
| `sensor.grid_to_battery` | Grid power charging battery (W) |
| `sensor.battery_to_house` | Battery discharge to house (W) |
| `sensor.grid_to_house` | Grid power consumed by house (W) |

All sensors are always >= 0 Watts.

## Prerequisites

- [Huawei Solar integration](https://github.com/wlcrs/huawei_solar) installed and working
- The following source sensors must exist:
  - `sensor.inverter_active_power` -- Total AC bus power
  - `sensor.inverter_input_power` -- Pure DC solar input
  - `sensor.power_meter_active_power` -- Grid power meter
  - `sensor.batteries_charge_discharge_power` -- Battery power

> **Note:** Entity names may differ if you have multiple inverters or renamed entities. The config flow lets you pick any sensor entity.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu (top right) > **Custom repositories**
3. Add `https://github.com/emanuelbesliu/homeassistant-huawei-solar-power-flow` with category **Integration**
4. Click **Install**
5. Restart Home Assistant
6. Go to **Settings > Devices & Services > Add Integration**
7. Search for **Huawei Solar Power Flow**
8. Configure the source entities (defaults work for standard single-inverter setups)

### Manual

1. Download the latest release from [GitHub Releases](https://github.com/emanuelbesliu/homeassistant-huawei-solar-power-flow/releases)
2. Copy the `custom_components/huawei_solar_power_flow` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Go to **Settings > Devices & Services > Add Integration**
5. Search for **Huawei Solar Power Flow**

## Huawei SUN2000 Sign Conventions

These were verified against FusionSolar live data:

| Sensor | Positive | Negative |
|---|---|---|
| `inverter_active_power` | Producing (AC output) | Consuming (AC battery charging) |
| `inverter_input_power` | Always >= 0 (pure DC solar) | N/A |
| `power_meter_active_power` | **Exporting** to grid | **Importing** from grid |
| `batteries_charge_discharge_power` | Charging | Discharging |

> **Important:** `inverter_active_power` is the total AC bus power (includes battery flows). `inverter_input_power` is pure solar. This integration uses `inverter_input_power` for solar-specific calculations.

## Zero-Rejection Filter

The Huawei Solar Modbus TCP connection periodically drops for 10-120 seconds. During reconnection, individual registers may momentarily return 0 while others still have stale values. This produces false readings (e.g., home consumption jumping to 0W then back to 3000W).

This integration filters these glitches: if a computed value drops to 0W while the previous value was above a threshold (50W default, 100W for solar), the previous value is held. Once the source sensors stabilize, normal values flow through.

## Tesla-Style Solar Power Card

This integration is designed to work with the [Tesla Style Solar Power Card](https://github.com/reptilex/tesla-style-solar-power-card). Add this to your Lovelace dashboard:

```yaml
type: custom:tesla-style-solar-power-card
name: Solar

# Flow entities (directional, always positive W)
grid_to_house_entity: sensor.grid_to_house
grid_to_battery_entity: sensor.grid_to_battery
generation_to_grid_entity: sensor.generation_to_grid
generation_to_house_entity: sensor.solar_consumption
generation_to_battery_entity: sensor.generation_to_battery
battery_to_house_entity: sensor.battery_to_house

# Bubble/total entities (displayed in circles)
grid_entity: sensor.power_meter_active_power
house_entity: sensor.home_consumption
generation_entity: sensor.solar_production
battery_entity: sensor.batteries_charge_discharge_power
battery_extra_entity: sensor.batteries_state_of_capacity

# Display in Watts
show_w_not_kw: 1
```

## Energy Dashboard

For the HA Energy Dashboard, you need energy sensors (kWh), not power sensors (W). Add integration sensors in `configuration.yaml`:

```yaml
sensor:
  - platform: integration
    source: sensor.solar_production
    name: "Solar Daily Production"
    unique_id: solar_daily_production
    unit_prefix: k
    round: 2
    method: left

  - platform: integration
    source: sensor.grid_consumption
    name: "Grid Daily Import"
    unique_id: grid_daily_import
    unit_prefix: k
    round: 2
    method: left

  - platform: integration
    source: sensor.grid_feed_in
    name: "Grid Daily Export"
    unique_id: grid_daily_export
    unit_prefix: k
    round: 2
    method: left

  - platform: integration
    source: sensor.home_consumption
    name: "Home Daily Consumption"
    unique_id: home_daily_consumption
    unit_prefix: k
    round: 2
    method: left
```

> **Note:** Do NOT use `sensor.inverter_total_yield` for solar production in the Energy Dashboard -- it includes battery discharge energy and will overcount.

## Tested Hardware

- **Inverter:** Huawei SUN2000-8KTL-M1
- **Battery Controller:** LUNA2000-10KW-C1
- **Battery Module:** LUNA2000-7-E1 (7 kWh)

Should work with other Huawei SUN2000 models and LUNA2000 battery combinations.

## License

[MIT](LICENSE)

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://github.com/hacs/integration
[release-badge]: https://img.shields.io/github/v/release/emanuelbesliu/homeassistant-huawei-solar-power-flow
[release-url]: https://github.com/emanuelbesliu/homeassistant-huawei-solar-power-flow/releases
[license-badge]: https://img.shields.io/github/license/emanuelbesliu/homeassistant-huawei-solar-power-flow
## ☕ Support the Developer

If you find this project useful, consider buying me a coffee!

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/emanuelbesliu)

[license-url]: https://github.com/emanuelbesliu/homeassistant-huawei-solar-power-flow/blob/main/LICENSE
