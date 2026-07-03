# Reference Data

This folder contains development reference material for the project.

Only anonymised protocol fixtures and generic capability notes may be committed here.

## Allowed Content

Examples of acceptable committed content:

- Sanitised TCP status payloads
- Generic controller capability samples
- Protocol field notes
- Test fixtures with generic zone names
- Synthetic payloads created for unit tests
- Non-identifying example system profiles

## Do Not Commit

Never commit:

- IP addresses
- MAC addresses
- WiFi passwords
- WPA keys
- Device serial numbers
- Controller IDs
- Public IP addresses
- Router configuration
- Home or room names
- Occupancy-related timestamps
- Raw packet captures
- Home Assistant secrets
- MQTT credentials
- Screenshots containing personal information

## Folder Structure

```text
reference_data/
├── anonymised/       Sanitised protocol samples suitable for review
├── notes/            Generic field notes and example profiles
├── raw/              Local-only files, ignored by Git
└── private/          Local-only files, ignored by Git
```

## Sanitising Status Payloads

Before creating a fixture:

1. Replace actual zone names with generic names such as `Zone A`, `Zone B`, or `Living`.
2. Remove IP addresses and hostnames.
3. Remove timestamps that identify household activity.
4. Remove module identifiers and serial numbers.
5. Remove any credentials or WiFi details.
6. Confirm the payload does not reveal the physical home layout.

Use descriptive fixture names, for example:

```text
heating_multi_zone_idle.json
heating_multi_zone_active.json
cooling_single_zone_idle.json
evaporative_manual_pump_on.json
fault_active_unknown_code.json
```