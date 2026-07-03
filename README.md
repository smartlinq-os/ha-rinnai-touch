# Rinnai Touch for Home Assistant

A local-only Home Assistant custom integration for Rinnai Touch and Brivis Touch WiFi HVAC controllers.

The integration is intended to communicate directly with compatible Rinnai Touch WiFi modules over the local network. It does not require a Rinnai cloud account, Homebridge, MQTT, Node-RED, or external internet access.

> [!WARNING]
> This project is under active development and is not ready for production HVAC control.
>
> The initial release is read-only by design. Command and control support will only be enabled after the local protocol parser and connection handling have been validated safely.

## Goals

- Local-only communication with the Rinnai Touch WiFi module
- No cloud dependency
- Support for Rinnai and Brivis Touch-compatible systems
- Support for heating, refrigerated cooling and evaporative cooling where protocol data permits
- Support for single-setpoint and multi-setpoint zoning
- Safe, reliable Home Assistant-native entities
- Eventual HACS compatibility

## Planned Features

### Phase 1: Read-only

- Local TCP connection to the WiFi module
- Automatic capability detection
- Current temperatures
- Zone information
- Connection diagnostics
- Last successful status time
- Fault status
- Downloadable diagnostics with sensitive values redacted

### Later phases

- HVAC mode control
- Target temperature control
- Zone enable and disable controls
- Fan control
- Evaporative pump control
- Manual and schedule controls where validated
- UDP discovery

## Requirements

- Home Assistant
- A supported Rinnai Touch or Brivis Touch WiFi module accessible on the local network
- The module IP address or hostname
- TCP connectivity to the module, normally on port `27847`

## Installation

Installation instructions will be added once the integration reaches a usable beta stage.

The intended installation method is HACS.

## Configuration

The planned configuration flow will request:

- Module host or IP address
- Optional TCP port, defaulting to `27847`
- Optional friendly installation name

Hardware capabilities, zones and available functions should be detected from the module status payload rather than entered manually.

## Compatibility

This project is being designed to support a range of Rinnai and Brivis Touch WiFi module installations.

Current protocol observations include support for:

- Gas heating
- Refrigerated or add-on cooling
- Evaporative cooling
- Single-setpoint systems
- Multi-setpoint zoned systems
- Zones U and A through D

Actual compatibility remains under validation.

## Troubleshooting

This project will include a standalone read-only protocol probe to assist with diagnostics.

Potential network check:

```bash
nc -vz -w 3 <MODULE_IP> 27847
```

Do not run experimental command tools against an HVAC module unless you understand the impact and have stopped any competing local integration, such as Homebridge.

### Module connection constraints

- The module may permit only one active local TCP client at a time. Concurrent use by Homebridge, a probe tool, another integration, or the TouchApp's local connection may cause connection conflicts. Behaviour may vary by module firmware and remains subject to local validation. Upstream documentation reports that the TouchApp may still operate via the Rinnai cloud while a local connection is held.
- Upstream observations report that the module drops idle TCP connections after roughly five minutes, and that it may refuse connections for a period if a socket is closed abruptly or reopened too quickly. These behaviours are pending local validation.

## Development

The project uses the following Homebridge implementation as a protocol reference:

```text
mantorok1/homebridge-rinnai-touch-platform
```

The upstream Homebridge project is licensed under Apache License 2.0.

This integration is independently implemented in Python using Home Assistant architecture and conventions.

See `AGENT_SCOPE.md` for the development architecture, safety constraints and planned milestones.

## Privacy and Diagnostics

Do not commit raw captures, packet traces or logs containing:

- IP addresses
- MAC addresses
- WiFi credentials or WPA keys
- Device serial numbers
- Home or room names
- Occupancy-related timestamps
- Other personally identifying home information

Only anonymised status fixtures should be committed under `tests/fixtures` or `reference_data/anonymised`.

## Licence

This project is licensed under the Apache License 2.0. See `LICENSE`.

See `NOTICE` for attribution information.