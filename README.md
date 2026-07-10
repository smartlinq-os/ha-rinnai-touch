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

### Passive protocol probe

`scripts/rinnai_probe.py` is a user-run, strictly passive capture tool for gathering private local protocol evidence (frame cadence, idle-disconnect timing, framing, sequences, field shape). It transmits no bytes to the module.

Before a first capture:

1. Stop Homebridge and any other local integration or client that talks to the module; the module may permit only one local TCP connection, and the local Rinnai/Brivis app may conflict while the capture runs.
2. Run the probe with the explicit acknowledgement flag. The default capture length is 360 seconds (six minutes) — keep at least that for the first real capture so idle-disconnect behaviour can be observed:

```bash
python scripts/rinnai_probe.py --host <MODULE_IP> --confirm-passive-capture
```

Raw output is written privately under `reference_data/raw/` (git-ignored). Raw captures can contain household data and must never be committed; each capture includes a notes file with the redaction checklist to follow before any sanitised fixture is created. Any future decision about a transport keepalive depends on the evidence these passive captures provide.

### Passive session recycle

This integration is passive and read-only: it never sends a keepalive, command, acknowledgement, polling request, or other session-maintenance byte to the module.

On the one local N-BW2 installation validated so far, the module streamed status normally for roughly five minutes and then stopped sending frames while the TCP connection stayed open from the integration's point of view. Rather than wait indefinitely on a silent connection, the integration closes and reopens the socket after a period of read-idle silence and lets its normal reconnect logic bring the stream back — still without transmitting anything.

During normal operation this means you may see a brief connectivity drop of around 10–12 seconds approximately every 7–8 minutes. Data freshness should stay "fresh" through this cycle: a multi-day field validation run on one installation showed the stream recovering on the first reconnect attempt in almost every cycle. Full evidence and its limits are recorded in `docs/protocol_assumptions.md` (ledger items A2, A15, A16) — this behaviour is validated on one installation only, and is not a guarantee for every module or firmware.

If data freshness becomes persistently stale, connections start being refused, or sessions repeatedly end without any status frame, disable the integration's config entry and collect logs rather than leaving it running or repeatedly reloading it.

Do not repeatedly reload or re-enable the integration while the module is in a refused-connection state. The module is reported to dislike rapid reconnects, and repeated reloads can make a refused state worse or harder to clear.

This behaviour was validated with Homebridge and any other local TCP client disabled. Local multi-client behaviour is unvalidated — keep competing local clients disabled while testing.

### Logging

For normal troubleshooting, enable debug logging for the transport client and info logging for the coordinator:

```yaml
logger:
  default: warning
  logs:
    custom_components.rinnai_touch.client: debug
    custom_components.rinnai_touch.coordinator: info
```

This shows session lifecycle, recycle, and reconnect activity without flooding the log.

For deep field debugging, enable debug logging for the whole integration:

```yaml
logger:
  default: warning
  logs:
    custom_components.rinnai_touch: debug
```

This is noisier: Home Assistant logs a coordinator update for every valid status frame received — roughly once per second while the module is streaming — so full debug logging can produce a large volume of lines across a normal five-minute stream window. Use it only when you need that level of detail, and turn it back down afterwards.

For a fuller guide to collecting and sanitising logs before opening an issue, plus the issue templates themselves, see [`docs/support/log_collection.md`](docs/support/log_collection.md).

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

For the release process, see [`docs/support/release_checklist.md`](docs/support/release_checklist.md).

### Local development environment

The project is offline-only at this milestone: it contains no networking code, and the test suite runs without network access, hardware, or a Home Assistant instance.

Requirements: Python 3.12 or newer, pip 25.1 or newer (for dependency-group support).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --group dev
```

Run the tests:

```bash
pytest
```

Run the linter and type checker:

```bash
ruff check .
mypy custom_components tests
```

Home Assistant test fixtures (`pytest-homeassistant-custom-component`) live in the separate `ha-test` dependency group and are not needed until HA-dependent tests exist.

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