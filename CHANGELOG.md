# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-03-05

### Fixed
- Fix ImportError on recent Home Assistant versions: replaced removed `EventType` import from `homeassistant.helpers.typing` with `Event` from `homeassistant.core`
- Ignore `brands` check in HACS validation (not required for custom repositories)

## [1.0.0] - 2026-03-05

### Added
- Initial release
- 12 derived power flow sensors from Huawei Solar integration
- Correct sign conventions verified with FusionSolar
- Zero-rejection Modbus glitch filtering
- Config flow UI with entity selectors and defaults
- HACS compatible
- Tesla-style solar power card configuration example

### Sensors Created
- Grid Consumption / Grid Feed In
- Solar Production / Solar Consumption
- Home Consumption
- Battery Charge Power / Battery Discharge Power
- Generation To Grid / Generation To Battery
- Grid To Battery / Grid To House / Battery To House
